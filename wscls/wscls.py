import argparse
import os
import asyncio
import json
from time import time
from typing import Any

import aiohttp
from aiohttp.http_websocket import WSMessage
from textual.app import App, ComposeResult
from textual.widgets import TextArea
from textual.widgets import Input
from textual.widgets import RichLog
from textual.widgets import Button
from textual.widgets import OptionList
from textual.widgets import Select
from textual.widgets import Label
from textual.widgets import TabbedContent
from textual.widgets import TabPane
from textual.widgets import Switch
from textual.widget import Widget
from textual.containers import Horizontal
from textual.widgets.option_list import Option
from textual.events import Event
from textual.message import Message
from textual.containers import Grid
from textual.screen import Screen
from textual import on
from textual import work


class ConfigurationAddGrid(Widget):
    DEFAULT_CSS = """
    ConfigurationAddGrid {
        width: 1fr;
        height: 5;
        layout: grid;
        grid-size-columns: 2;
        grid-columns: 1fr 15;
    }
    """


class MainGrid(Grid):
    DEFAULT_CSS = """
    MainGrid {
        width: 1fr;
        height: 1fr;
        layout: grid;
        grid-rows: 3 60% 15%
    }
    """


class ConnectContainer(Widget):
    DEFAULT_CSS = """
    ConnectContainer {
        width: 1fr;
        height: auto;
        layout: grid;
        grid-columns: 1fr 15;
        grid-size-columns: 2;
    }
    """

class HorizontalHAuto(Widget):
    DEFAULT_CSS = """
    HorizontalHAuto {
        width: 1fr;
        height: auto;
        layout: horizontal;
    }
    """


class State:
    def __init__(self, filename: str = None):
        if not filename:
            filename = os.path.join(os.path.expanduser("~"), '.wscls.json')
        self.configuration_name = 'default'
        self.state_filename = filename

        self.configurations = {
            'default': self.default_configuration
        }

    @property
    def default_configuration(self):
        return {
            'url': '',
            'headers': {},
            'autoping': False,
            'text': '',
            'auto_reconnect': True,
            'ssl_check': True
        }

    def get_configuration(self):
        try:
            return self.configurations[self.configuration_name]
        except KeyError:
            self.configuration_name = list(self.configurations.keys())[0]
            return self.configurations[self.configuration_name]

    def get_value(self, key):
        return self.get_configuration().get(key)

    def set_value(self, key: str, value: Any):
        self.get_configuration()[key] = value

    def add_configuration(self, name: str, data=None):
        if data is None:
            data = self.default_configuration

        self.configurations[name] = data

    def delete_configuration(self, name: str):
        if name in self.configurations:
            del self.configurations[name]
            if not self.configurations:
                self.add_configuration('default')
            if self.configuration_name == name:
                self.configuration_name = list(self.configurations.keys())[0]

    def load(self):
        if not os.path.exists(self.state_filename):
            return
        try:
            with open(self.state_filename, 'r', encoding='utf8') as fil:
                state_file = json.load(fil)
                self.configurations = state_file.get('configurations', self.configurations)
                self.configuration_name = state_file.get('selected_configuration', 'default')
        except Exception as exc:
            print(exc)

    def save(self):
        state_data = {
            'configurations': self.configurations,
            'selected_configuration': self.configuration_name
        }

        with open(self.state_filename, 'w', encoding='utf8') as fil:
            json.dump(state_data, fil)


class AddHeaderScreen(Screen):
    @on(Button.Pressed, '#add')
    def add(self, message: Message):
        self.dismiss((self.query_one('#header_name').value, self.query_one('#header_value').value))

    @on(Button.Pressed, '#cancel')
    def cancel(self, message: Message):
        self.dismiss(None)

    @on(Input.Submitted)
    def submit(self, message: Message):
        self.dismiss((self.query_one('#header_name').value, self.query_one('#header_value').value))

    def on_key(self, event: Event):
        if event.key == 'escape':
            self.dismiss(None)

    def compose(self) -> ComposeResult:
        yield Label('Add Header')
        yield Input(placeholder='Name', id='header_name')
        yield Input(placeholder='Value', id='header_value')
        yield Horizontal(
            Button('Add', id='add'),
            Button('Cancel', id='cancel')
        )


class AddressInput(Input):
    pass


class AddHeaderMenuButton(Button):
    class Message(Message):
        pass

    def on_button_pressed(self, event: Event):
        self.post_message(self.Message())


class SendTextArea(TextArea):
    def on_text_area_changed(self, event: Event):
        self.app.state.set_value('text', self.text)

    def on_key(self, event: Event):
        if event.key == 'ctrl+r':
            self.parent.query_one('#send_message').action_press()


class WsApp(App):
    def __init__(self, state):
        super().__init__()
        self._connect_task = None
        self._ws = None
        self._connecting = None
        self.state = state

    async def process_incomming_ws_message(self, log: RichLog, msg: WSMessage):
        log = self.query_one('#ws_sessions_log')

        if msg.type == aiohttp.WSMsgType.ERROR:
            log.write('[red]Error: ')
        elif msg.type == aiohttp.WSMsgType.PONG:
            rtt = round((time() - float(msg.data.decode('utf-8'))) * 1000, 3)
            log.write(f'[cyan]Pong received, RTT: {rtt} ms')
        else:
            log.write(f'[cyan]Received: {msg.data}')

    def on_connected(self, log: RichLog):
        log.write(f'[green]Connected to: {self.state.get_value("url")}')
        log.styles.border = ('heavy', 'green')
        self.query_one(SendTextArea)

    def on_disconnected(self, log: RichLog):
        log.write('[red]Disconnected')
        log.styles.border = ('heavy', 'red')

    async def connect(self):
        log = self.query_one('#ws_sessions_log')
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    ssl_check = None if self.state.get_value('ssl_check') else False

                    async with session.ws_connect(
                        self.state.get_value('url'),
                        headers=self.state.get_value('headers'),
                        autoping=self.state.get_value('autoping'),
                        ssl=ssl_check
                    ) as ws:
                        try:
                            self._ws = ws
                            self.on_connected(log)
                            async for msg in ws:
                                await self.process_incomming_ws_message(log, msg)

                            log.write(f'[red]Closed by remote side with code: {ws.close_code}')
                        except Exception as exc:
                            log.write(f'[red]Error: {exc}')
                        finally:
                            self.on_disconnected(log)
            except Exception as exc:
                log.write(f'[red]Error: {exc}')

            if not self.state.get_value('auto_reconnect'):
                break

            await asyncio.sleep(1)
            log.write(f'[yellow]Reconnecting to: {self.state.get_value("url")}')

    def refresh_headers(self):
        headers_list = self.query_one('#headers_list')
        headers_list.clear_options()
        headers_list.add_options(
            [Option(f'{k}: {v}', id=k) for k, v in self.state.get_value('headers').items()]
        )

    def refresh_configurations(self):
        config_list = self.query_one('#configurations_list')
        config_list.set_options([(x, x) for x in self.state.configurations.keys()])
        config_list.value = self.state.configuration_name

    def refresh_fields(self):
        self.query_one(AddressInput).value = self.state.get_value('url')
        self.query_one(SendTextArea).text = self.state.get_value('text')
        self.query_one('#autoping').value = self.state.get_value('autoping')
        self.query_one('#auto_reconnect').value = self.state.get_value('auto_reconnect')
        self.query_one('#ssl_check').value = self.state.get_value('ssl_check')
        self.refresh_headers()

    @work
    async def on_add_header_menu_button_message(self, message: Message):
        screen = AddHeaderScreen()
        screen.styles.width = 40
        screen.styles.height = 10
        screen.styles.border = ('heavy', 'white')
        data = await self.push_screen_wait(
            screen
        )

        if not data:
            return

        self.state.get_value('headers')[data[0]] = data[1]

        self.refresh_headers()

    def on_mount(self):
        self.refresh_fields()
        self.refresh_configurations()

    @on(Button.Pressed, '#connect')
    async def on_connect_button_message(self, message: Message):
        log = self.query_one('#ws_sessions_log')
        addr = self.query_one(AddressInput).value

        if self._connect_task:
            button = self.query_one('#connect')
            button.label = 'Connect'

            self._connect_task.cancel()
            self._ws = None

        if self._connecting:
            self._connecting = False
            return

        button = self.query_one('#connect')
        button.label = 'Disconnect'
        self._connecting = True


        self.state.set_value('url', addr)
        log.write(f'Connecting to: {addr}')

        self._connect_task = asyncio.create_task(self.connect())

    @on(Button.Pressed, '#send_message')
    async def send_message(self, message: Message):
        textar = self.query_one(SendTextArea)
        text = ''
        log = self.query_one('#ws_sessions_log')
        if self._ws:
            try:
                if textar.selected_text:
                    text = textar.selected_text
                else:
                    text = textar.text

                await self._ws.send_str(text)
                log.write(f'[yellow]Sent: {text}')
            except Exception as exc:
                log.write(f'[red]Error: {exc}')

    @on(Button.Pressed, '#delete_header')
    def delete_header(self, message: Message):
        headers_list = self.query_one('#headers_list')

        if headers_list.highlighted is None:
            return

        selected = headers_list.get_option_at_index(headers_list.highlighted)
        if selected:
            del self.state.get_value('headers')[selected.id]
            self.refresh_headers()

    @on(AddressInput.Submitted)
    def submit_connect(self, message: Message):
        self.query_one('#connect').action_press()

    @on(Button.Pressed, '#ping')
    async def ping(self):
        log = self.query_one('#ws_sessions_log')
        if self._ws:
            try:
                await self._ws.ping(str(time()))
                log.write('[yellow]Ping sent')
            except Exception as exc:
                log.write(f'[red]Error: {exc}')

    @on(Button.Pressed, '#add_configuration')
    def add_configuration(self, message: Message):
        name_field = self.query_one('#configuration_name')
        if name_field.value:
            self.state.add_configuration(name_field.value)
            self.refresh_configurations()
            name_field.clear()

    @on(Button.Pressed, '#delete_configuration')
    def delete_configuration(self, message: Message):
        config_list = self.query_one('#configurations_list')
        selected = config_list.value
        if selected:
            self.state.delete_configuration(selected)
            self.refresh_configurations()

    @on(Switch.Changed, '#autoping')
    def autoping_switch(self, message: Message):
        self.state.set_value('autoping', message.value)

    @on(Switch.Changed, '#auto_reconnect')
    def auto_reconnect_switch(self, message: Message):
        self.state.set_value('auto_reconnect', message.value)

    @on(Switch.Changed, '#ssl_check')
    def ssl_check_switch(self, message: Message):
        self.state.set_value('ssl_check', message.value)

    @on(Select.Changed, '#configurations_list')
    def change_configuration(self, message: Message):
        selected = message.value

        if selected:
            self.state.configuration_name = selected
            self.refresh_fields()

    def compose_request_tab(self):
        yield MainGrid(
            ConnectContainer(
                AddressInput(self.state.get_value('url'), placeholder='URL', id='address'),
                Button('Connect', id='connect')
            ),
            RichLog(highlight=True, markup=True, id='ws_sessions_log'),
            SendTextArea(self.state.get_value('text')),
            HorizontalHAuto(
                Button('Send', id='send_message'),
                Button('Ping', id='ping')
            )
        )

    def compse_options_tab(self):
        yield Label('Headers')
        yield OptionList(id='headers_list')
        yield HorizontalHAuto(
            AddHeaderMenuButton('Add'),
            Button('Delete', id='delete_header')
        )
        yield HorizontalHAuto(
            Label('\nAuto ping:'),
            Switch(self.state.get_value('autoping'), animate=True, id='autoping')
        )
        yield HorizontalHAuto(
            Label('\nAuto reconnect:'),
            Switch(self.state.get_value('auto_reconnect'), animate=True, id='auto_reconnect')
        )
        yield HorizontalHAuto(
            Label('\nCheck SSL:'),
            Switch(self.state.get_value('ssl_check'), animate=True, id='ssl_check')
        )
        yield Label('Configurations')

        yield HorizontalHAuto(
            Select([('', '')], id='configurations_list'),
            Button('Delete', id='delete_configuration')
        )

        yield ConfigurationAddGrid(
            Input(placeholder='Name', id='configuration_name'),
            Button('Add config', id='add_configuration')
        )

    def compose(self) -> ComposeResult:
        with TabbedContent(initial='Request'):
            with TabPane('Request', id='Request'):
                yield from self.compose_request_tab()

            with TabPane('Options', id='Options'):
                yield from self.compse_options_tab()


def main():
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument('--config', '-c', dest='config_path', default=None)
        args = parser.parse_args()

        state = State(args.config_path)
        state.load()
        app = WsApp(state)
        app.run()
    finally:
        state.save()


if __name__ == '__main__':
    main()