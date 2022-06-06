import json
from uuid import uuid4
from fastapi.encoders import jsonable_encoder
from data_handlers.action import MotionItem


# Handler for the list of motions available to Pepper
# Handlers for sessions and actions may store motions unknown to this, therefore unknown to Pepper
class MotionsHandler:
    def __init__(self, motions_file, actions_handler):
        self.motions = dict()
        self.save_file = motions_file
        self.actions_master = actions_handler

        with open(motions_file) as f:
            motions_list = json.load(f)['motions']
        for motion in motions_list:
            self.motions[motion['Name']] = MotionItem.parse_obj(motion)
        self.actions_master.add_actions(self.motions.values())

    def add_motion(self, name, group="Remote", path=""):
        if name not in self.motions.keys():
            motion = (MotionItem.parse_obj({"ID": uuid4(),
                                            "Group": group,
                                            "Delay": 0,
                                            "Name": name,
                                            "FilePath": path}))
            self.motions[name] = motion
            self.actions_master.add_action(motion)

    def add_motions(self, movements):
        for motion_name in movements['moves']:
            self.add_motion(motion_name)
        self.save_motions()

    def save_motions(self):
        with open(self.save_file, "w") as f:
            f.write(json.dumps(jsonable_encoder(self.get_motions())))

    def get_motions(self):
        return {"motions": list(self.motions.values())}

    def get_motion_by_id(self, motion_id):
        return next((x for x in self.motions.values() if x.ID == motion_id), None)

    def get_motion_by_name(self, motion_name):
        return self.motions.get(motion_name)
