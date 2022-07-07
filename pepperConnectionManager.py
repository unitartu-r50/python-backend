import json
import asyncio
import time
from uuid import UUID
from anyio import Event
from typing import List
from fastapi import WebSocket, WebSocketDisconnect


class PepperConnectionManager:
    def __init__(self, motions_handler, actions_handler):
        self.motions_master = motions_handler
        self.actions_master = actions_handler
        self.active_connections: List[WebSocket] = []
        self.active_commands = {}
        self.item_locks = {'MultiAction': None,
                           'UtteranceItem': None,
                           'MotionItem': None,
                           'ImageItem': None,
                           'URLItem': None}

    async def connect(self, websocket):
        await websocket.accept()
        self.active_connections.append(websocket)

        try:
            # Pepper sends its motions list on connection
            moves = await websocket.receive_json()
            self.motions_master.add_motions(moves)
            while True:
                data = await websocket.receive_json()

                # Pepper declares that an action has finished (indicated by the key 'action_*') ->
                #   -> store the exit status, notify the relevant send_command thread to return it.
                if any(x in data for x in ['action_success', 'action_error']):
                    result = list(data.keys())[0]
                    action_id = UUID(data[result])
                    if action_id not in self.active_commands.keys():
                        raise ValueError(f"Command ID mismatch! Received {data[result]}, had {self.active_commands.keys()}")
                    event = self.active_commands[action_id]['event']
                    self.active_commands[action_id]['result'] = result
                    await event.set()

                # Something else
                else:
                    print("Data: ", data)

        # Client disconnects
        except WebSocketDisconnect:
            self.disconnect(websocket)
            await self.log("Client disconnected")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def log(self, message: str):
        print(message)

    def get_status(self):
        if self.active_connections:
            return 1
        return 0

    # TODO: Return error codes?
    async def send_command(self, action_id):
        # Placeholder: grabbing the first connection, if available
        # TODO: Send to specific connection (concurrency)
        if len(self.active_connections) < 1:
            return {str(action_id): "action_error", 'message': "You're not connected to a robot!"}
        connection = self.active_connections[0]

        action = self.actions_master.get_action(action_id)
        if action is None:
            return {action_id: "action_error", 'message': f"Faulty action ID: {action_id}"}

        action_type = type(action).__name__

        # Ignore commands if one of the same type is already active
        if self.item_locks[action_type]:
            return {action_id: "action_warning", 'message': "Please wait for the previous command to finish!"}
        # If the type is 'MultiAction', ...
        if action_type == 'MultiAction':
            # ... check that the action actually has any valid child actions to execute
            if not action.get_children(must_be_valid=True):
                return {str(action_id): "action_success", "message": "Action had no children to execute!"}
            # ... and check for locks on each of its child actions
            if action.UtteranceItem and action.UtteranceItem.Phrase and self.item_locks['UtteranceItem']\
                    or action.MotionItem and action.MotionItem.Name and self.item_locks['MotionItem']\
                    or action.ImageItem and action.ImageItem.Name and self.item_locks['ImageItem']\
                    or action.URLItem and action.URLItem.URL and self.item_locks['URLItem']:
                return {str(action_id): "action_error", 'message': "A child command is blocked, please wait for the previous command to finish!"}

        # Locking the action type, adding the in-progress-command to memory
        self.item_locks[action_type] = action.ID
        self.active_commands[action.ID] = dict()

        # Event to await
        task_finished = Event()
        self.active_commands[action.ID]['event'] = task_finished

        # If the command is to execute multiple actions, call them all individually
        if action_type == 'MultiAction':
            self.active_commands[action.ID]['children'] = set()
            self.active_commands[action.ID]['errors'] = list()

            # Create and memorize the workers first to avoid race conditions,
            # e.g a worker finishing before another is declared.
            subcommand_args_list = []
            for child_action in action.get_children(must_be_valid=True):
                subcommand_args_list.append([self, connection, self.motions_master, self.actions_master,
                                             child_action.ID, action.ID])

                self.active_commands[action.ID]['children'].add(child_action.ID)

            # Start the workers
            for subcommand_args in subcommand_args_list:
                asyncio.get_event_loop().create_task(send_subcommand(*subcommand_args))

        else:
            # Send the command to Pepper
            await connection.send_text(json.dumps(action.get_command_payload()))

        # Wait for the command to be carried out (notification performed by this.connect)
        await task_finished.wait()

        # Construct the message to be returned
        if action_type == 'MultiAction':
            # If any children returned errors, construct an error message; otherwise report success
            message = ", ".join(list(filter(lambda x: x != "", self.active_commands[action.ID]['errors'])))
            if message:
                result = "action_error"
            else:
                result = "action_success"
        else:
            # Report the outcome of the action
            result = self.active_commands[action.ID]['result']
            message = ""

        # Clear the current command, release the type lock, return the result
        self.active_commands.pop(action.ID)
        self.item_locks[action_type] = None
        return {str(action.ID): result, "message": message}


# Simplified PepperConnectionManager.send_command() to send MultiAction subcommands on a different thread
async def send_subcommand(connection_manager, connection, motions_handler, actions_handler, action_id, parent_command_id):
    # If the SingleAction does not exist, terminate early
    action = actions_handler.get_action(action_id)
    if action is None:
        connection_manager.active_commands[parent_command_id]['errors'].append(f"Faulty action ID: {action_id}")
        connection_manager.active_commands[parent_command_id]['children'].remove(action_id)
        time.sleep(0.1)
        if not connection_manager.active_commands[parent_command_id]['children']:
            await connection_manager.active_commands[parent_command_id]['event'].set()
        return

    action_type = type(action).__name__

    # If the motion handler (thus, Pepper) is unaware of a motion, asking Pepper to fulfill it will result in a hang
    if action_type == 'MotionItem' and motions_handler.get_motion_by_id(action_id) is None:
        connection_manager.active_commands[parent_command_id]['errors'].append(f"Unknown motion {action_id}")
        connection_manager.active_commands[parent_command_id]['children'].remove(action_id)
        time.sleep(0.1)
        if not connection_manager.active_commands[parent_command_id]['children']:
            await connection_manager.active_commands[parent_command_id]['event'].set()
        return

    # Lock checks and connection selection are performed by the caller, skipping them

    # Locking the action type, adding the in-progress-command to memory
    connection_manager.item_locks[action_type] = action.ID
    connection_manager.active_commands[action.ID] = dict()

    # Event to await
    task_finished = Event()
    connection_manager.active_commands[action.ID]['event'] = task_finished

    # Send the command to Pepper
    await connection.send_text(json.dumps(action.get_command_payload()))

    # Wait for the command to be carried out (notification performed by this.connection_manager.connect)
    await task_finished.wait()

    # Clear the current command (after memorizing the stored result), release the type lock
    result = connection_manager.active_commands[action.ID]['result']
    connection_manager.active_commands.pop(action.ID)
    connection_manager.item_locks[action_type] = None

    # If the result is an error, store the type of the failed action; otherwise, store an empty string
    connection_manager.active_commands[parent_command_id]['errors'].append("" if result == 'action_success' else action_type)

    # Remove this command from the in-progress list of the parent,
    # notify the parent if all of its children have finished.
    connection_manager.active_commands[parent_command_id]['children'].remove(action.ID)
    if not connection_manager.active_commands[parent_command_id]['children']:
        await connection_manager.active_commands[parent_command_id]['event'].set()
