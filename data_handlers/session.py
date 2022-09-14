import json
from uuid import UUID, uuid4
from pydantic import BaseModel
from pydantic.schema import List, Optional
from fastapi.encoders import jsonable_encoder

from data_handlers.action import MultiAction, initialise_child_ids, rename_files


# TODO: Are all these IDs, names, groups etc. really necessary?

# A question, consisting of one or more MultiActions
class SessionItem(BaseModel):
    ID: UUID = None
    Actions: List[MultiAction]


# An entire session, composed of questions (SessionItems)
class Session(BaseModel):
    ID: UUID = None
    Name: str
    Description: Optional[str]
    Items: List[SessionItem]


# Set missing IDs, remove redundant UtteranceItem pronunciation attributes
def session_cleanup(session):
    zero = UUID('00000000-0000-0000-0000-000000000000')
    if session.ID is None or session.ID == zero:
        session.ID = uuid4()
    for session_item in session.Items:
        if session_item.ID is None or session_item.ID == zero:
            session_item.ID = uuid4()
        for action in session_item.Actions:
            if action.ID is None or action.ID == zero:
                action.ID = uuid4()
            initialise_child_ids(action)
            action.UtteranceItem.pronunciation_cleanup()


class SessionsHandler:
    def __init__(self, sessions_file, actions_handler, motions_handler):
        self.actions_master = actions_handler
        self.motions_master = motions_handler
        self.save_file = sessions_file

        # Load data from a JSON savefile
        with open(sessions_file) as f:
            sessions_list = json.load(f)['sessions']

        # Replacing dictionaries with objects where viable, bottom-up
        self.sessions = []
        for session in sessions_list:
            self.sessions.append(Session.parse_obj(session))
            self.add_session_actions_to_action_master(self.sessions[-1])

    def save_sessions(self):
        with open(self.save_file, "w") as f:
            f.write(json.dumps(jsonable_encoder(self.get_sessions())))

    async def dict_to_session_rename(self, session):
        zero = UUID('00000000-0000-0000-0000-000000000000')
        if session['ID'] is None or session['ID'] == zero:
            session['ID'] = uuid4()
        for session_item in session['Items']:
            primary_action = True
            if session_item['ID'] is None or session_item['ID'] == zero:
                session_item['ID'] = uuid4()
            action_objects = []
            for action in session_item['Actions']:
                if action['ID'] is None or action['ID'] == zero:
                    action['ID'] = uuid4()
                # Action class changes and checks for any sessions created with the old setup
                if 'SayItem' in action.keys():
                    action['UtteranceItem'] = action.pop('SayItem')
                    action['UtteranceItem']['Pronunciation'] = ""
                    action['MotionItem'] = action.pop('MoveItem')
                    action_object = MultiAction.parse_obj(action)
                    
                    if not (action_object.UtteranceItem.Phrase and action_object.UtteranceItem.FilePath):
                        action_object.UtteranceItem.flash()

                    action_object.MotionItem.attribute_correction(self.motions_master)

                    if action_object.ImageItem.FilePath is None or action_object.ImageItem.FilePath == "":
                        action_object.ImageItem.flash()

                    if action_object.URLItem.URL is None or action_object.URLItem.URL == "":
                        action_object.URLItem.flash()
                else:
                    action_object = MultiAction.parse_obj(action)

                # Cleanup missing/zero-value child action IDs
                initialise_child_ids(action_object)
                # Rename media files from UUIDs to sha256 hashes when importing sessions
                fixed_action = await rename_files(action_object)

                if primary_action:
                    fixed_action.PrimaryAction = True
                    primary_action = False

                action_objects.append(fixed_action)
                self.actions_master.add_action(fixed_action)
                self.actions_master.add_actions(fixed_action.get_children())
            session_item['Actions'] = action_objects

    def _link_motions(self, session):
        for session_item in session.Items:
            for action in session_item.Actions:
                if (handler_action := self.motions_master.get_motion_by_name(action.MotionItem.Name)) is not None:
                    action.MotionItem.ID = handler_action.ID
                    action.MotionItem.Group = handler_action.Group
                    action.MotionItem.FilePath = handler_action.FilePath
                else:
                    action.MotionItem.flash()

    def get_sessions(self):
        return {"sessions": self.sessions}

    def get_sorted_sessions(self):
        return {'sessions': sorted(self.sessions, key=lambda x: x.Name)}

    def get_session(self, ID):
        return next((x for x in self.sessions if x.ID == ID), None)

    def get_session_index(self, ID):
        for index, session in enumerate(self.get_sorted_sessions()['sessions']):
            if session.ID == UUID(ID):
                return index
        return None

    def get_session_item(self, ID):
        for session in self.sessions:
            for item in session.Items:
                if item.ID == ID:
                    return {'session_item': item}
        return {'error': f"Item with ID {ID} wasn't found!"}

    # Requires a dict-based session with no Action/SessionItem/etc. objects
    async def import_session(self, session):
        await self.dict_to_session_rename(session)
        self.sessions.append(Session.parse_obj(session))
        self.save_sessions()

    def add_session_actions_to_action_master(self, session, overwrite=False):
        for session_item in session.Items:
            primary_action = True
            for action in session_item.Actions:
                if primary_action:
                    action.PrimaryAction = True
                    primary_action = False
                self.actions_master.add_action(action, overwrite=overwrite)
                for child_action in action.get_children():
                    self.actions_master.add_action(child_action, overwrite=overwrite)

    def update_session(self, ID, updated_session):
        for index, session in enumerate(self.sessions):
            if session.ID == ID:
                self._link_motions(updated_session)
                session_cleanup(updated_session)
                self.sessions[index] = updated_session
                self.add_session_actions_to_action_master(updated_session, overwrite=True)
                self.save_sessions()
                return {'message': 'Session updated!'}
        return {'error': f"Couldn't find session {ID}!"}

    def add_session(self, session):
        self._link_motions(session)
        session_cleanup(session)
        self.add_session_actions_to_action_master(session)
        self.sessions.append(session)
        self.save_sessions()

    def remove_session(self, session_id):
        self.sessions = list(filter(lambda x: x.ID != session_id, self.sessions))
        self.save_sessions()

    def remove_action(self, action_id):
        for session in self.sessions:
            for session_item in session.Items:
                for action in session_item.Actions:
                    if action.ID == action_id:
                        session_item.Actions.remove(action)
                        return {'message': 'Action removed!'}
        return {'error': f'No action with ID {action_id}'}
