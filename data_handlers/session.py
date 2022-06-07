import json
from uuid import UUID, uuid4
from pydantic import BaseModel
from pydantic.schema import List, Optional
from fastapi.encoders import jsonable_encoder

from .action import rename_files
from data_handlers.action import MultiAction, initialise_child_ids


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


def initialise_identifiers(session):
    if session.ID is None:
        session.ID = uuid4()
    for session_item in session.Items:
        if session_item.ID is None:
            session_item.ID = uuid4()
        for action in session_item.Actions:
            if type(action) == MultiAction:
                if action.ID is None:
                    action.ID = uuid4()
                initialise_child_ids(action)


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

    async def _dict_to_session_rename(self, session):
        for session_item in session['Items']:
            action_objects = []
            for action in session_item['Actions']:
                # Action class change for any sessions created with the old setup
                if 'SayItem' in action.keys():
                    action['UtteranceItem'] = action.pop('SayItem')
                    action['MotionItem'] = action.pop('MoveItem')
                    if (handler_action := self.motions_master.get_motion_by_name(action['MotionItem']['Name'])) is not None:
                        action['MotionItem']['ID'] = handler_action.ID

                # Rename media files from UUIDs to sha256 hashes when importing sessions
                print(action['MotionItem']['ID'] is None)
                print(action['MotionItem']['ID'])
                print(action['MotionItem'])
                fixed_action = await rename_files(MultiAction.parse_obj(action))

                action_objects.append(fixed_action)
                self.actions_master.add_action(fixed_action)
                self.actions_master.add_actions(fixed_action.get_children())
            session_item['Actions'] = action_objects

    def get_sessions(self):
        return {"sessions": self.sessions}

    def get_session(self, ID):
        return next((x for x in self.sessions if x.ID == ID), None)

    def get_session_item(self, ID):
        for session in self.sessions:
            for item in session.Items:
                if item.ID == ID:
                    return {'session_item': item}
        return {'error': f"Item with ID {ID} wasn't found!"}

    # Requires a dict-based session with no Action/SessionItem/etc. objects
    async def import_session(self, session):
        await self._dict_to_session_rename(session)
        self.sessions.append(Session.parse_obj(session))
        self.save_sessions()

    def add_session_actions_to_action_master(self, session, overwrite=False):
        for session_item in session.Items:
            for action in session_item.Actions:
                self.actions_master.add_action(action, overwrite=overwrite)
                for child_action in action.get_children():
                    self.actions_master.add_action(child_action, overwrite=overwrite)

    def update_session(self, ID, updated_session):
        for index, session in enumerate(self.sessions):
            if session.ID == ID:
                initialise_identifiers(updated_session)
                self.sessions[index] = updated_session
                self.add_session_actions_to_action_master(updated_session, overwrite=True)
                self.save_sessions()
                return {'message': 'Session updated!'}
        return {'error': f"Couldn't find session {ID}!"}

    def add_session(self, session):
        initialise_identifiers(session)
        self.sessions.append(session)
        self.add_session_actions_to_action_master(session)
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
