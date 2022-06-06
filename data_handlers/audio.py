import json
from data_handlers.action import UtteranceItem
from fastapi.encoders import jsonable_encoder


class AudioShortcutsHandler:
    def __init__(self, audio_file, actions_master):
        with open(audio_file) as f:
            audio_list = json.load(f)['data']

        self.audio_items = [UtteranceItem.parse_obj(audio_item) for audio_item in audio_list]
        actions_master.add_actions(self.audio_items)

    def get_audio_metadata(self):
        return {'data': self.audio_items}

    def get_single_audio_metadata(self, ID):
        return {'data': next((x for x in self.audio_items if x.ID == ID), None)}

    def _save_audio_metadata(self):
        with open("data/quick_audio.json", "w") as f:
            f.write(json.dumps(jsonable_encoder(self.get_audio_metadata())))
            print(f"saved:\n{self.get_audio_metadata()}")

    def add_audio(self, utterance_item):
        self.audio_items.append(utterance_item)
        self._save_audio_metadata()

    def remove_audio(self, audio_id):
        # The file is not deleted
        self.audio_items = list(filter(lambda x: x.ID != audio_id, self.audio_items))
        self._save_audio_metadata()
