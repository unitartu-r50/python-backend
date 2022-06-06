import os
import json
from uuid import UUID, uuid4
from base64 import b64encode, urlsafe_b64encode

from pydantic import BaseModel
from pydantic.schema import Optional
from fastapi.encoders import jsonable_encoder

from .file_operations import hash_phrase_to_filename, hash_file_to_filename


class Action(BaseModel):
    ID: UUID = None
    Group: Optional[str]

    def get_command_payload(self):
        raise NotImplementedError(type(self).__name__ + ".get_command_payload() is unimplemented")


class SingleAction(Action):
    Delay: int

    # SingleAction is functionally an interface, it's not meant to be instantiated
    def get_command_payload(self):
        raise NotImplementedError


def encode_url(url):
    # Encoding to avoid special characters breaking URLs (requires a bytes-like object),
    # then casting back to strings since bytes are not JSON-serializable.
    return urlsafe_b64encode(url.encode()).decode()


class UtteranceItem(SingleAction):
    Phrase: str
    FilePath: str

    def get_command_payload(self):
        return {"command": "say",
                "content": encode_url(self.FilePath),
                "name": self.Phrase,
                "delay": self.Delay,
                "id": str(self.ID)}


class ImageItem(SingleAction):
    Name: str
    FilePath: str

    def get_command_payload(self):
        with open(self.FilePath, "rb") as image:
            return {"command": "show_image",
                    # "content": encode_url(self.FilePath),
                    "content": b64encode(image.read()).decode(),
                    "name": self.Name,
                    "delay": self.Delay,
                    "id": str(self.ID)}


class MotionItem(SingleAction):
    Name: str
    FilePath: str

    def get_command_payload(self):
        return {"command": "move",
                "content": "",
                "name": self.Name,
                "delay": self.Delay,
                "id": str(self.ID)}


class URLItem(SingleAction):
    Name: str
    URL: str

    def get_command_payload(self):
        return {"command": "show_url",
                "content": encode_url(self.URL),
                "name": self.Name,
                "delay": self.Delay,
                "id": str(self.ID)}


class MultiAction(Action):
    Name: str = None
    UtteranceItem: Optional[UtteranceItem]
    MotionItem: Optional[MotionItem]
    ImageItem: Optional[ImageItem]
    URLItem: Optional[URLItem]

    # MultiAction commands are not supposed to be sent to the robot,
    # send individual commands (Utterance, Motion etc.) asynchronously instead.
    def get_command_payload(self):
        raise NotImplementedError

    def get_children(self):
        children = []
        if self.UtteranceItem is not None and self.UtteranceItem.ID is not None:
            children.append(self.UtteranceItem)
        if self.ImageItem is not None and self.ImageItem.ID is not None:
            children.append(self.ImageItem)
        if self.MotionItem is not None and self.MotionItem.ID is not None:
            children.append(self.MotionItem)
        if self.URLItem is not None and self.URLItem.ID is not None:
            children.append(self.URLItem)
        return children


def initialise_child_ids(action: MultiAction):
    # If ID-less child actions exist, grant them IDs
    if action.UtteranceItem and action.UtteranceItem.Phrase and action.UtteranceItem.ID is None:
        action.UtteranceItem.ID = uuid4()
    if action.MotionItem and action.MotionItem.Name and action.MotionItem.ID is None:
        action.MotionItem.ID = uuid4()
    if action.ImageItem and action.ImageItem.FilePath and action.ImageItem.ID is None:
        action.ImageItem.ID = uuid4()
    if action.URLItem and action.URLItem.URL and action.URLItem.ID is None:
        action.URLItem.ID = uuid4()


def _name_is_uuid(filepath):
    is_uuid = True
    try:
        UUID(os.path.basename(filepath).rsplit('.', 1)[0])
    except ValueError:
        is_uuid = False
    return is_uuid


async def rename_files(action: MultiAction):
    if action.UtteranceItem and action.UtteranceItem.FilePath and _name_is_uuid(action.UtteranceItem.FilePath):
        if not action.UtteranceItem.Phrase:
            raise ValueError(f"Corrupted session file - missing phrase for {action.UtteranceItem.FilePath}")
        new_path = os.path.join('data', 'uploads', f"{hash_phrase_to_filename(action.UtteranceItem.Phrase)}.{action.UtteranceItem.FilePath.rsplit('.', 1)[-1]}")
        os.rename(action.UtteranceItem.FilePath, new_path)
        action.UtteranceItem.FilePath = new_path
    if action.ImageItem and action.ImageItem.FilePath and _name_is_uuid(action.ImageItem.FilePath):
        with open(action.ImageItem.FilePath, "rb") as image_file:
            file_hash = await hash_file_to_filename(image_file)
        new_path = os.path.join('data', 'uploads', f"{file_hash}.{action.ImageItem.FilePath.rsplit('.', 1)[-1]}")
        os.rename(action.UtteranceItem.FilePath, new_path)
        action.UtteranceItem.FilePath = new_path
    return action


class ActionShortcutsHandler:
    def __init__(self, quick_actions_file, actions_handler):
        self.actions_master = actions_handler

        with open(quick_actions_file) as f:
            actions_list = json.load(f)['data']

        self.actions = []
        for action in actions_list:
            self.actions.append(MultiAction.parse_obj(action))

        self.actions_master.add_actions(self.actions)

    def _save_actions(self):
        with open("data/quick_actions.json", "w") as f:
            f.write(json.dumps(jsonable_encoder(self.get_actions())))

    def get_actions(self):
        return {"data": self.actions}

    def add_action(self, multiaction):
        multiaction.ID = uuid4()
        multiaction.UtteranceItem.ID = uuid4()
        multiaction.MotionItem.ID = uuid4()
        multiaction.ImageItem.ID = uuid4()
        multiaction.URLItem.ID = uuid4()
        self.actions.append(multiaction)
        self.actions_master.add_action(multiaction)
        self._save_actions()

    def remove_action(self, action_id):
        for index, listed_action in enumerate(self.actions):
            if listed_action.ID == action_id:
                self.actions.pop(index)
                break
        self._save_actions()


# TODO: Should actions be removed from this handler when removed elsewhere?
class ActionsHandler:
    def __init__(self):
        self.actions = dict()

    def add_action(self, action, overwrite=False):
        if action.ID not in self.actions.keys() or overwrite:
            self.actions[action.ID] = action

    def add_actions(self, actions):
        for action in actions:
            self.add_action(action)

    def get_action(self, action_id: UUID):
        return self.actions[action_id] if action_id in self.actions.keys() else None
