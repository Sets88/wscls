import argparse
import os
import asyncio
import json
import shutil
from time import time
from typing import Any
import tempfile

import aiohttp
from aiohttp.http_websocket import WSMessage
from textual.app import App, ComposeResult
from textual.app import Binding
from textual.reactive import reactive
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
from textual.widgets import Footer
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.widgets.option_list import Option
from textual.events import Event
from textual.message import Message
from textual.containers import Grid
from textual.screen import ModalScreen
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
        grid-rows: 4 1 5fr 1fr 30%
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
        self.loaded = False

    @property
    def default_configuration(self):
        return {
            'url': '',
            'headers': {},
            'autoping': False,
            'texs': {'': ''},
            'auto_reconnect': True,
            'ssl_check': True
        }

    def get_configuration(self):
        try:
            return self.configurations[self.configuration_name]
        except KeyError:
            self.configuration_name = list(self.configurations.keys())[0]
            return self.configurations[self.configuration_name]

    def get_value(self, key, default=None):
        return self.get_configuration().get(key, default)

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
                self.loaded = True
        except Exception as exc:
            print(exc)

    def save(self):
        state_data = {
            'configurations': self.configurations,
            'selected_configuration': self.configuration_name
        }

        if self.loaded:
            with tempfile.NamedTemporaryFile(mode="w", buffering=1) as fil:
                fil.write(json.dumps(state_data))
                fil.flush()
                shutil.copy(fil.name, self.state_filename)


class WsRichLog(RichLog):
    BINDINGS = [
        Binding('s', 'toggle_scroll'),
        Binding('c', 'clear'),
        Binding('w', 'toggle_wrap'),
    ]

    def action_toggle_wrap(self):
        self.wrap = not self.wrap
        self.app.query_one('#log_status').word_wrap = self.wrap

    def action_clear(self):
        self.lines.clear()
        self.refresh()

    def action_toggle_scroll(self):
        self.auto_scroll = not self.auto_scroll
        self.refresh()
        self.app.query_one('#log_status').auto_scroll = self.auto_scroll


class EditModalScreen(ModalScreen):
    CSS = """
        EditModalScreen {
            align: center middle;
        }
        EditModalScreen > Vertical {
            background: #101030;
            border: tall #303040;
            height: 12;
            width: 70;
        }
        EditModalScreen #content {
            margin: 0 1;
        }
        EditModalScreen Label {
            margin: 0 1;
        }
        EditModalScreen #buttons {
            margin: 0 1;
        }
    """
    def __init__(self, title, name=None) -> None:
        self.key_name = name
        self.modal_title = title
        super().__init__()

    @on(Button.Pressed, '#add')
    def add(self, message: Message):
        self.dismiss(self.query_one('#text_name').value)

    @on(Button.Pressed, '#save')
    def save(self, message: Message):
        self.dismiss(self.query_one('#text_name').value)

    @on(Button.Pressed, '#cancel')
    def cancel(self, message: Message):
        self.dismiss(None)

    @on(Input.Submitted)
    def submit(self, message: Message):
        self.dismiss(self.query_one('#text_name').value)

    def on_key(self, event: Event):
        if event.key == 'escape':
            self.dismiss(None)

    def compose(self) -> ComposeResult:
        with Vertical():
            with Vertical(id='content'):
                yield Label(self.modal_title)
                yield Input(placeholder='Name', id='text_name', value=self.key_name)

                if self.key_name:
                    yield Horizontal(
                        Button('Save', id='save'),
                        Button('Cancel', id='cancel'),
                        id='buttons'
                    )
                else:
                    yield Horizontal(
                        Button('Add', id='add'),
                        Button('Cancel', id='cancel'),
                        id='buttons'
                    )


class EditHeaderScreen(ModalScreen):
    CSS = """
        EditHeaderScreen {
            align: center middle;
        }
        EditHeaderScreen > Vertical {
            background: #101030;
            border: tall #303040;
            height: 12;
            width: 70;
        }
        EditHeaderScreen #content {
            margin: 0 1;
        }
        EditHeaderScreen Label {
            margin: 0 1;
        }
        EditHeaderScreen #buttons {
            margin: 0 1;
        }
    """
    def __init__(self, name=None, value=None) -> None:
        self.key_name = name
        self.value = value
        super().__init__()

    @on(Button.Pressed, '#add')
    def add(self, message: Message):
        self.dismiss((self.query_one('#header_name').value, self.query_one('#header_value').value))

    @on(Button.Pressed, '#save')
    def save(self, message: Message):
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
        with Vertical():
            with Vertical(id='content'):
                if self.key_name:
                    yield Label('Edit Header')
                else:
                    yield Label('Add Header')
                yield Input(placeholder='Name', id='header_name', value=self.key_name)
                yield Input(placeholder='Value', id='header_value', value=self.value)

                if self.key_name:
                    yield Horizontal(
                        Button('Save', id='save'),
                        Button('Cancel', id='cancel'),
                        id='buttons'
                    )
                else:
                    yield Horizontal(
                        Button('Add', id='add'),
                        Button('Cancel', id='cancel'),
                        id='buttons'
                    )


class AddressInput(Input):
    pass


class LogStatus(Label):
    DEFAULT_CSS = """
    LogStatus {
        dock: right;
    }
    """
    word_wrap = reactive(False)
    auto_scroll = reactive(True)

    def render(self):
        return (f" Word wrapping: [cyan]w[/cyan] ({'On' if self.word_wrap else 'Off'}) Clear: "
            f"[cyan]c[/cyan] Scroll: [cyan]s[/cyan] ({'On' if self.auto_scroll else 'Off'})")


class SendTextArea(TextArea):
    BINDINGS = [
        Binding('ctrl+r', 'send_message'),
        Binding('ctrl+f', 'send_message')
    ]
    def on_text_area_changed(self, event: Event):
        self.app.state.get_value('texts', {})[self.app.state.get_value('text_selected')] = self.text

    async def action_send_message(self):
        self.app.query_one('#send_message').action_press()


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

    def on_connected(self, log: RichLog, url: str):
        text = f'[green]Connected to: {self.state.get_value("url")}'
        log.write(text)
        self.set_status_text(text)
        log.styles.border = ('heavy', 'green')

    def on_disconnected(self, log: RichLog):
        text = '[red]Disconnected'
        self.set_status_text(text)
        log.write(text)
        log.styles.border = ('heavy', 'red')

    async def connect(self):
        log = self.query_one('#ws_sessions_log')
        while True:
            try:
                async with aiohttp.ClientSession() as session:
                    ssl_check = None if self.state.get_value('ssl_check') else False
                    url = self.state.get_value('url')

                    async with session.ws_connect(
                        url,
                        headers=self.state.get_value('headers'),
                        autoping=self.state.get_value('autoping'),
                        ssl=ssl_check
                    ) as ws:
                        try:
                            self._ws = ws
                            self.on_connected(log, url)
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

    def refresh_texts(self):
        text_list = self.query_one('#texts')
        values = [(x, x) for x in self.state.get_value('texts', {'': ''}).keys()]
        text_list.set_options(values)
        text_list.value = self.state.get_value('text_selected', values[0][0])

    def refresh_configurations(self):
        config_list = self.query_one('#configurations_list')
        config_list.set_options([(x, x) for x in self.state.configurations.keys()])
        config_list.value = self.state.configuration_name

    def refresh_fields(self):
        self.query_one(AddressInput).value = self.state.get_value('url')
        self.query_one(SendTextArea).text = (
            self.state.get_value('texts', {'': ''}).get(self.state.get_value('text_selected'), '')
        )
        self.query_one('#autoping').value = self.state.get_value('autoping')
        self.query_one('#auto_reconnect').value = self.state.get_value('auto_reconnect')
        self.query_one('#ssl_check').value = self.state.get_value('ssl_check')
        self.refresh_headers()

    @work
    @on(Button.Pressed, '#add_header')
    async def on_add_header_menu_button_message(self, message: Message):
        screen = EditHeaderScreen()

        data = await self.push_screen_wait(
            screen
        )

        if not data:
            return

        self.state.get_value('headers')[data[0]] = data[1]

        self.refresh_headers()

    @work
    @on(Button.Pressed, '#edit_header')
    async def on_edit_header_menu_button_message(self, message: Message):
        headers_list = self.query_one('#headers_list')

        if headers_list.highlighted is None:
            return

        selected = headers_list.get_option_at_index(headers_list.highlighted)

        if not selected.id:
            return

        screen = EditHeaderScreen(name=selected.id, value=self.state.get_value('headers')[selected.id])

        data = await self.push_screen_wait(
            screen
        )

        if not data:
            return

        self.state.get_value('headers').pop(selected.id)
        self.state.get_value('headers')[data[0]] = data[1]

        self.refresh_headers()

    @work
    @on(Button.Pressed, '#add_text')
    async def on_add_text_select_item(self, message: Message):
        screen = EditModalScreen('Add Text')

        data = await self.push_screen_wait(
            screen
        )

        if not data:
            return

        if self.state.get_value('texts') and data in self.state.get_value('texts'):
            # Exists
            return

        if not self.state.get_value('texts'):
            self.state.set_value('texts', {})

        self.state.get_value('texts')[data] = ''
        self.refresh_texts()

    @work
    @on(Button.Pressed, '#edit_text')
    async def on_edit_edit_text_select_item(self, message: Message):
        config_list = self.query_one('#texts')
        selected = config_list.value

        if selected is None:
            return

        screen = EditModalScreen('Edit text', name=selected)

        data = await self.push_screen_wait(
            screen
        )

        if not data:
            return

        if self.state.get_value('texts') and data in self.state.get_value('texts'):
            # Exists
            return

        self.state.get_value('texts')[data] = self.state.get_value('texts').pop(selected)
        self.state.set_value('text_selected', data)

        self.refresh_texts()

    def on_mount(self):
        self.refresh_fields()
        self.refresh_configurations()
        self.refresh_texts()

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

    @on(Button.Pressed, '#delete_text')
    def delete_text(self, message: Message):
        texts_list = self.query_one('#texts')

        selected = texts_list.value

        if selected is None:
            return

        self.state.get_value('texts').pop(selected.id)

        self.refresh_texts()

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

    @work
    @on(Button.Pressed, '#add_configuration')
    async def on_add_configuration(self, message: Message):
        screen = EditModalScreen('Add Configuration')

        data = await self.push_screen_wait(
            screen
        )

        if not data:
            return

        if self.state.get_value('configurations') and data in self.state.get_value('configurations'):
            # Exists
            return

        self.state.add_configuration(data)
        self.refresh_configurations()

    @on(Button.Pressed, '#delete_configuration')
    def delete_configuration(self, message: Message):
        config_list = self.query_one('#configurations_list')
        selected = config_list.value
        if selected:
            self.state.delete_configuration(selected)
            self.state.configuration_name = list(self.state.configurations.keys())[0]
            self.refresh_fields()
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
            self.refresh_texts()

    @on(Select.Changed, '#texts')
    def change_texts(self, message: Message):
        selected = message.value

        if selected and selected != Select.BLANK:
            self.state.set_value('text_selected', selected)
            self.state.set_value('text', self.state.get_value('texts')[selected])
            self.refresh_fields()

    def compose_request_tab(self):
        yield MainGrid(
            ConnectContainer(
                AddressInput(self.state.get_value('url'), placeholder='URL', id='address'),
                Button('Connect', id='connect')
            ),
            Horizontal(
                Label('Disconnected', id='status'),
                LogStatus('', id='log_status'),
            ),
            WsRichLog(highlight=True, markup=True, id='ws_sessions_log'),
            HorizontalHAuto(
                Select([('', '')], id='texts'),
                Button('Add', id='add_text'),
                Button('Delete', id='delete_text'),
                Button('Edit', id='edit_text')
            ),
            SendTextArea(''),
            HorizontalHAuto(
                Button('Send', id='send_message'),
                Button('Ping', id='ping')
            )
        )

    def compse_options_tab(self):
        yield Vertical(
            Label('Headers'),
            HorizontalHAuto(
                OptionList(id='headers_list'),
                Button('Add', id='add_header'),
                Button('Delete', id='delete_header'),
                Button('Edit', id='edit_header'),
            ),
            HorizontalHAuto(
                Label('\nAuto ping:'),
                Switch(self.state.get_value('autoping'), animate=True, id='autoping')
            ),
            HorizontalHAuto(
                Label('\nAuto reconnect:'),
                Switch(self.state.get_value('auto_reconnect'), animate=True, id='auto_reconnect')
            ),
            HorizontalHAuto(
                Label('\nCheck SSL:'),
                Switch(self.state.get_value('ssl_check'), animate=True, id='ssl_check')
            ),
            Label('Configurations'),
            HorizontalHAuto(
                Select([('', '')], id='configurations_list'),
                Button('Add', id='add_configuration'),
                Button('Delete', id='delete_configuration'),
                Button('Edit', id='edit_configuration'),
            )
        )

    def set_status_text(self, text: str):
        self.query_one('#status').update(text)

    def compose(self) -> ComposeResult:
        with TabbedContent(initial='Request'):
            with TabPane('Request', id='Request'):
                yield from self.compose_request_tab()

            with TabPane('Options', id='Options'):
                yield from self.compse_options_tab()
        yield Footer()


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