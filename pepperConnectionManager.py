import json
import time
import asyncio

from uuid import UUID
from anyio import Event
from random import randint
from fastapi import WebSocketDisconnect


class LockManager:
    def __init__(self):
        self.active_commands = {}
        self.item_locks = {'MultiAction': {},
                           'UtteranceItem': {},
                           'MotionItem': {},
                           'ImageItem': {},
                           'URLItem': {}}

    def flash(self):
        self.__init__()


class PepperConnectionManager:
    def __init__(self, motions_handler, actions_handler, record_manager):
        # Seconds before an action can be overriden
        self.override_time = 5
        # Seconds before an unresponsive client gets unlinked from a robot
        self.connection_clear_time = 30

        self.motions_master = motions_handler
        self.actions_master = actions_handler
        self.active_connections = {}

        self.record_manager = record_manager

        asyncio.create_task(self.clear_connections())

    def clear_locks(self, connection_id):
        self.active_connections[connection_id]["lock_manager"].flash()

    def get_status(self, connection_id):
        if connection_id in self.active_connections and self.active_connections[connection_id]["linked"]:
            # Refresh the checked time to keep the connection linked (see clear_connections)
            self.active_connections[connection_id]['checked'] = time.time()
            return 1
        return 0

    async def send_auth(self, key, content="Enter this code to the web client to connect to this robot", target=None):
        if not target:
            target = self.active_connections[key]['connection_obj']
        await target.send_text(json.dumps({"command": "auth",
                                           "content": content,
                                           "name": None,
                                           "delay": 0,
                                           "id": key}))

    # Clear clientless connections every self.connection_clear_time seconds
    async def clear_connections(self):
        next_call = time.time()
        while True:
            for key in self.active_connections:
                if self.active_connections[key]["checked"] and next_call - self.active_connections[key]["checked"] > self.connection_clear_time:
                    self.active_connections[key]["linked"] = False
                    self.active_connections[key]["checked"] = None
                    print(key)
                    if self.record_manager.recording_connection == key:
                        self.record_manager.stop_recording(key)
                    await self.send_auth(key)

            next_call = next_call + 10
            await asyncio.sleep(next_call - time.time())

    async def connect(self, websocket):
        auth_code = None
        await websocket.accept()
        try:
            # Pepper sends its motions list over the connection
            moves = await websocket.receive_json()
            self.motions_master.add_motions(moves)

            if len(self.active_connections) >= 1000:
                auth_code = "ERR!"
                content = "The server is at capacity!"
            else:
                auth_code = str(randint(0, 1000)).zfill(4)
                content = "Enter this code to the web client to connect to this robot"
                while auth_code in self.active_connections:
                    auth_code = str(randint(0, 1000)).zfill(4)

            await self.send_auth(auth_code, content=content, target=websocket)

            if auth_code == "ERR!":
                return

            lock_manager = LockManager()
            self.active_connections[auth_code] = {"connection_obj": websocket,
                                                  "lock_manager": lock_manager,
                                                  "linked": False,
                                                  "checked": None}
            while True:
                data = await websocket.receive_json()

                # Pepper declares that an action has finished (indicated by the key 'action_*') ->
                #   -> store the exit status, notify the relevant send_command thread to return it.
                if any(x in data for x in ['action_success', 'action_error']):
                    result = list(data.keys())[0]
                    action_id = UUID(data[result])
                    if action_id not in lock_manager.active_commands.keys():
                        raise ValueError(f"Command ID mismatch! Received {data[result]}, had {lock_manager.active_commands.keys()}")
                    event = lock_manager.active_commands[action_id]['event']
                    lock_manager.active_commands[action_id]['result'] = result
                    await event.set()

                # Something else
                else:
                    print("Data: ", data)

        # Client disconnects
        except WebSocketDisconnect:
            if auth_code and auth_code != "ERR!":
                self.active_connections.pop(auth_code)
            print("Client disconnected")

    async def link(self, connection_id):
        if connection_id in self.active_connections:
            if not self.active_connections[connection_id]['linked']:
                self.active_connections[connection_id]['linked'] = True
                self.active_connections[connection_id]['checked'] = time.time()
                await self.clear_fragment(connection_id)
                return {"message": "Connected to a robot!"}
            else:
                return {"error": "A client is already connected to this robot!"}
        return {"error": "No robot was found under this code!"}

    async def unlink(self, connection_id):
        if connection_id in self.active_connections:
            if self.active_connections[connection_id]['linked']:
                self.active_connections[connection_id]['linked'] = False
                self.active_connections[connection_id]['checked'] = time.time()
                await self.send_auth(connection_id)
                return {"message": "Disconnected from the robot!"}
            return {"error": "No client is linked to this robot!"}
        return {"error": "No robot was found under this code!"}

    async def unlockable_child(self, child_action_type, lock_manager):
        if lock_manager.item_locks[child_action_type]['has_blocked'] and time.time() - lock_manager.item_locks[child_action_type]['start_time'] > self.override_time:
            await lock_manager.active_commands[lock_manager.item_locks[child_action_type]]['event'].set()
            return True
        else:
            lock_manager.item_locks[child_action_type]['has_blocked'] = True
            return False

    async def clear_fragment(self, connection_id):
        connection = self.active_connections[connection_id]["connection_obj"]
        await connection.send_text(json.dumps({"command": "clear_fragment",
                                               "content": None,
                                               "name": None,
                                               "delay": 0,
                                               "id": None}))
        return {"message": "Stop command sent!"}

    async def clear_image(self, connection_id):
        connection = self.active_connections[connection_id]["connection_obj"]
        await connection.send_text(json.dumps({"command": "clear_image",
                                               "content": None,
                                               "name": None,
                                               "delay": 0,
                                               "id": None}))
        return {"message": "Clear command sent!"}

    # TODO: Return error codes?
    async def send_command(self, action_id, connection_id):
        connection = self.active_connections[connection_id]["connection_obj"]
        lock_manager = self.active_connections[connection_id]["lock_manager"]

        action = self.actions_master.get_action(action_id)
        if action is None:
            return {action_id: "action_error", 'message': f"Faulty action ID: {action_id}"}

        action_type = type(action).__name__

        # TODO: Fix the underlying issue, remove workaround
        # After ending blocking actions in another action call, unexpected behaviour appears
        # (new actions and their locks do not get stored in memory etc.).
        # However, once the process finishes (including the command_pepper() call from main.py),
        # everything returns to normal. Therefore, the issue must lie with asyncio and this implementation.
        # Workaround: fail with a special response code and have the client call the action again.
        lockbreak = False

        # Check if an action of the same type is already active
        if lock_manager.item_locks[action_type]:
            # If the override lock has been cleared and the override time have elapsed, clear the blocking action, ...
            if lock_manager.item_locks[action_type]['has_blocked'] and time.time() - lock_manager.item_locks[action_type]['start_time'] > self.override_time:
                # If the blocking command is a MultiAction, the locked children must also be released.
                # The last child will release the parent on its own.
                if lock_manager.item_locks['MultiAction']:
                    for child_action_type in ['UtteranceItem', 'MotionItem', 'ImageItem', 'URLItem']:
                        if lock_manager.item_locks[child_action_type]:
                            await lock_manager.active_commands[lock_manager.item_locks[child_action_type]['UUID']]['event'].set()
                            lockbreak = True
                else:
                    await lock_manager.active_commands[lock_manager.item_locks[action_type]]['event'].set()
            # ... otherwise clear the override lock and display the warning.
            else:
                lock_manager.item_locks[action_type]['has_blocked'] = True
                return {action_id: "action_warning", 'message': "Please wait for the previous command to finish!"}
        # If the type is 'MultiAction', ...
        elif action_type == 'MultiAction':
            # ... check that the action actually has any valid child actions to execute ...
            if not action.get_children(must_be_valid=True):
                return {str(action_id): "action_warning", "message": "MultiAction has no children to execute!"}
            # ... and check for locks on each of its child actions.
            if action.UtteranceItem and action.UtteranceItem.Phrase and lock_manager.item_locks['UtteranceItem']:
                if await self.unlockable_child('UtteranceItem', lock_manager):
                    lockbreak = True
                else:
                    return {str(action_id): "action_error",
                            'message': "A child command is blocked, please wait for the previous command to finish!"}
            if action.MotionItem and action.MotionItem.Name and lock_manager.item_locks['MotionItem']:
                if await self.unlockable_child('MotionItem', lock_manager):
                    lockbreak = True
                else:
                    return {str(action_id): "action_error",
                            'message': "A child command is blocked, please wait for the previous command to finish!"}
            if action.ImageItem and action.ImageItem.Name and lock_manager.item_locks['ImageItem']:
                if await self.unlockable_child('ImageItem', lock_manager):
                    lockbreak = True
                else:
                    return {str(action_id): "action_error",
                            'message': "A child command is blocked, please wait for the previous command to finish!"}
            if action.URLItem and action.URLItem.URL and lock_manager.item_locks['URLItem']:
                if await self.unlockable_child('URLItem', lock_manager):
                    lockbreak = True
                else:
                    return {str(action_id): "action_error",
                            'message': "A child command is blocked, please wait for the previous command to finish!"}

        # See long comment above
        if lockbreak:
            return {str(action_id): "action_retry_required", "message": "redo required"}

        # Clearing the screen if required
        if action.PrimaryAction:
            await self.clear_image(connection_id)

        # Locking the action type, adding the in-progress-command to memory
        lock_manager.item_locks[action_type]['UUID'] = action.ID
        lock_manager.item_locks[action_type]['has_blocked'] = False
        lock_manager.active_commands[action.ID] = dict()

        # Event to await
        task_finished = Event()
        lock_manager.active_commands[action.ID]['event'] = task_finished

        # If the command is to execute multiple actions, call them all individually
        if action_type == 'MultiAction':
            lock_manager.active_commands[action.ID]['children'] = set()
            lock_manager.active_commands[action.ID]['errors'] = list()

            # Create and memorize the workers first to avoid race conditions,
            # e.g a worker finishing before another is declared.
            subcommand_args_list = []
            for child_action in action.get_children(must_be_valid=True):
                subcommand_args_list.append([lock_manager, connection, self.motions_master, self.actions_master,
                                             child_action.ID, action.ID])

                lock_manager.active_commands[action.ID]['children'].add(child_action.ID)

            # Start the workers
            for subcommand_args in subcommand_args_list:
                asyncio.get_event_loop().create_task(send_subcommand(*subcommand_args))

        else:
            # Send the command to Pepper
            await connection.send_text(json.dumps(action.get_command_payload()))

        # Save command start time (relevant for releasing locks on user override)
        lock_manager.item_locks[action_type]['start_time'] = time.time()

        # Record if relevant
        if self.record_manager.recording_connection == connection_id and not self.record_manager.recording_paused:
            self.record_manager.save_audio()
            self.record_manager.record_command(action_id)

        # Wait for the command to be carried out (notification performed by this.connect)
        await task_finished.wait()

        # Start recording if relevant
        if self.record_manager.recording_connection == connection_id and not self.record_manager.recording_paused:
            self.record_manager.recorder.record()

        # Construct the message to be returned
        if action_type == 'MultiAction':
            # If any children returned errors, construct an error message; otherwise report success
            message = ", ".join(list(filter(lambda x: x != "", lock_manager.active_commands[action.ID]['errors'])))
            if message:
                result = "action_error"
            else:
                result = "action_success"
        else:
            # Report the outcome of the action
            result = lock_manager.active_commands[action.ID]['result']
            message = ""

        # Clear the current command, release the type lock, return the result
        lock_manager.active_commands.pop(action.ID)
        lock_manager.item_locks[action_type] = {}

        return {str(action.ID): result, "message": message}


# Simplified PepperConnectionManager.send_command() to send MultiAction subcommands on a different thread
async def send_subcommand(lock_manager, connection, motions_handler, actions_handler, action_id, parent_command_id):
    # If the SingleAction does not exist, terminate early
    action = actions_handler.get_action(action_id)
    if action is None:
        lock_manager.active_commands[parent_command_id]['errors'].append(f"Faulty action ID: {action_id}")
        lock_manager.active_commands[parent_command_id]['children'].remove(action_id)
        time.sleep(0.1)
        if not lock_manager.active_commands[parent_command_id]['children']:
            await lock_manager.active_commands[parent_command_id]['event'].set()
        return

    action_type = type(action).__name__

    # If the motion handler (thus, Pepper) is unaware of a motion, asking Pepper to fulfill it will result in a hang
    if action_type == 'MotionItem' and motions_handler.get_motion_by_id(action_id) is None:
        lock_manager.active_commands[parent_command_id]['errors'].append(f"Unknown motion {action_id}")
        lock_manager.active_commands[parent_command_id]['children'].remove(action_id)
        time.sleep(0.1)
        if not lock_manager.active_commands[parent_command_id]['children']:
            await lock_manager.active_commands[parent_command_id]['event'].set()
        return

    # Lock checks and connection selection are performed by the caller, skipping them

    # Locking the action type, adding the in-progress-command to memory
    lock_manager.item_locks[action_type]['UUID'] = action.ID
    lock_manager.item_locks[action_type]['has_blocked'] = False
    lock_manager.active_commands[action.ID] = dict()

    # Event to await
    task_finished = Event()
    lock_manager.active_commands[action.ID]['event'] = task_finished

    # Send the command to Pepper
    await connection.send_text(json.dumps(action.get_command_payload()))

    # Save command start time (relevant for releasing erroneous locks)
    lock_manager.item_locks[action_type]['start_time'] = time.time()

    # Wait for the command to be carried out (notification performed by this.connection_manager.connect)
    await task_finished.wait()

    # Clear the current command (after memorizing the stored result), release the type lock
    if 'result' in lock_manager.active_commands[action.ID].keys():
        result = lock_manager.active_commands[action.ID]['result']
    else:
        result = ""
    lock_manager.active_commands.pop(action.ID)
    lock_manager.item_locks[action_type] = {}

    # If the result is an error, store the type of the failed action; otherwise, store an empty string
    lock_manager.active_commands[parent_command_id]['errors'].append("" if result == 'action_success' else action_type)

    # Remove this command from the in-progress list of the parent,
    # notify the parent if all of its children have finished.
    lock_manager.active_commands[parent_command_id]['children'].remove(action.ID)
    if not lock_manager.active_commands[parent_command_id]['children']:
        await lock_manager.active_commands[parent_command_id]['event'].set()
