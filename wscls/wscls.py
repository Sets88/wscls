import argparse
import os
import asyncio
import json
import shutil
from time import time
from typing import Any
import tempfile
from string import Template

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
from textual.containers import ScrollableContainer
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


def render_template(template: str, variables: dict) -> str:
    return Template(template).safe_substitute(variables)


class State:
    def __init__(self, filename: str = None):
        if not filename:
            filename = os.path.join(os.path.expanduser("~"), '.wscls.json')
        self.configuration_name = 'default'
        self.state_filename = filename

        self.configurations = {
            'default': self.default_configuration
        }
        self.globals = {}

        self.contexts = {'default': self.default_context}
        self.context_name = 'default'

        self.loaded = False

    @property
    def default_context(self):
        return {
            'context_variables': {}
        }

    @property
    def default_configuration(self):
        return {
            'url': '',
            'headers': {},
            'autoping': False,
            'texts': {'': ''},
            'auto_reconnect': True,
            'ssl_check': True
        }

    def get_configuration(self):
        try:
            return self.configurations[self.configuration_name]
        except KeyError:
            self.configuration_name = list(self.configurations.keys())[0]
            return self.configurations[self.configuration_name]

    def get_context(self):
        try:
            return self.contexts[self.context_name]
        except KeyError:
            self.context_name = list(self.contexts.keys())[0]
            return self.contexts[self.context_name]

    def get_variables(self):
        variables = dict()
        variables.update(self.globals)
        variables.update(self.get_context().get('context_variables', {}))
        return variables

    def get_value(self, key, default=None):
        if key == 'configurations':
            return self.configurations
        if key == 'globals':
            return self.globals
        if key == 'contexts':
            return self.contexts
        if key == 'context_variables':
            return self.get_context().get('context_variables')
        return self.get_configuration().get(key, default)

    def set_value(self, key: str, value: Any):
        self.get_configuration()[key] = value

    def delete_configuration(self, name: str):
        if name in self.configurations:
            del self.configurations[name]
            if not self.configurations:
                self.configurations['default'] = self.default_configuration
                self.context_name = 'default'
            if self.configuration_name == name:
                self.configuration_name = list(self.configurations.keys())[0]

    def delete_context(self, name: str):
        if name in self.contexts:
            del self.contexts[name]
            if not self.contexts:
                self.contexts['default'] = self.default_context
                self.context_name = 'default'
            if self.context_name == name:
                self.context_name = list(self.contexts.keys())[0]

    def load(self):
        if not os.path.exists(self.state_filename):
            self.loaded = True
            return
        try:
            with open(self.state_filename, 'r', encoding='utf8') as fil:
                state_file = json.load(fil)
                self.configurations = state_file.get('configurations', self.configurations)
                self.globals = state_file.get('globals', self.globals)
                self.configuration_name = state_file.get('selected_configuration', 'default')
                self.contexts = state_file.get('contexts', self.contexts)
                self.context_name = state_file.get('selected_context', 'default')
                self.loaded = True
        except Exception as exc:
            print(exc)

    def save(self):
        state_data = {
            'configurations': self.configurations,
            'selected_configuration': self.configuration_name,
            'globals': self.globals,
            'contexts': self.contexts,
            'selected_context': self.context_name

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


class EditNameModalScreen(ModalScreen):
    CSS = """
        EditNameModalScreen {
            align: center middle;
        }
        EditNameModalScreen > Vertical {
            background: #101030;
            border: tall #303040;
            height: 12;
            width: 70;
        }
        EditNameModalScreen #content {
            margin: 0 1;
        }
        EditNameModalScreen Label {
            margin: 0 1;
        }
        EditNameModalScreen #buttons {
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


class EditNameValueScreen(ModalScreen):
    CSS = """
        EditNameValueScreen {
            align: center middle;
        }
        EditNameValueScreen > Vertical {
            background: #101030;
            border: tall #303040;
            height: 12;
            width: 70;
        }
        EditNameValueScreen #content {
            margin: 0 1;
        }
        EditNameValueScreen Label {
            margin: 0 1;
        }
        EditNameValueScreen #buttons {
            margin: 0 1;
        }
    """
    def __init__(self, title, name=None, value=None) -> None:
        self.key_name = name
        self.value = value
        self.modal_title = title
        super().__init__()

    @on(Button.Pressed, '#add')
    def add(self, message: Message):
        self.dismiss((self.query_one('#imput_name').value, self.query_one('#input_value').value))

    @on(Button.Pressed, '#save')
    def save(self, message: Message):
        self.dismiss((self.query_one('#imput_name').value, self.query_one('#input_value').value))

    @on(Button.Pressed, '#cancel')
    def cancel(self, message: Message):
        self.dismiss(None)

    @on(Input.Submitted)
    def submit(self, message: Message):
        self.dismiss((self.query_one('#imput_name').value, self.query_one('#input_value').value))

    def on_key(self, event: Event):
        if event.key == 'escape':
            self.dismiss(None)

    def compose(self) -> ComposeResult:
        with Vertical():
            with Vertical(id='content'):
                yield Label(self.modal_title)
                yield Input(placeholder='Name', id='imput_name', value=self.key_name)
                yield Input(placeholder='Value', id='input_value', value=self.value)

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
        return (f" Word wrapping: [cyan]w[/cyan] ( {'On ' if self.word_wrap else 'Off'} ) Clear: "
            f"[cyan]c[/cyan] Scroll: [cyan]s[/cyan] ( {'On ' if self.auto_scroll else 'Off'} )   ")


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
        self._connecting_params = None
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
            if not self._connecting_params:
                break
            ssl_check = None if self._connecting_params['ssl_check'] else False
            url = self._connecting_params['url']
            headers = self._connecting_params['headers']
            autoping = self._connecting_params['autoping']

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(
                        url,
                        headers=headers,
                        autoping=autoping,
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
            if not self._connecting_params:
                break
            log.write(f'[yellow]Reconnecting to: {url}')

    def refresh_fields(self):
        self.query_one(AddressInput).value = self.state.get_value('url')
        self.query_one(SendTextArea).text = (
            self.state.get_value('texts', {'': ''}).get(self.state.get_value('text_selected'), '')
        )
        self.query_one('#autoping').value = self.state.get_value('autoping')
        self.query_one('#auto_reconnect').value = self.state.get_value('auto_reconnect')
        self.query_one('#ssl_check').value = self.state.get_value('ssl_check')
        self.query_one('#template_url').value = self.state.get_value('template_url')
        self.query_one('#template_data').value = self.state.get_value('template_data')
        self.refresh_headers()
        self.refresh_globals()
        self.refresh_contexts()
        self.refresh_context_variables()

    # Headers

    @work
    @on(Button.Pressed, '#add_header')
    async def on_add_header_menu_button_message(self, message: Message):
        key, _ = await self.edit_config_state_config_key_value('Add Header', 'headers')
        if key:
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

        key, _ = await self.edit_config_state_config_key_value('Edit Header', 'headers', orig_key_name=selected.id)

        if not key:
            return

        self.refresh_headers()

    @on(Button.Pressed, '#delete_header')
    def delete_header(self, message: Message):
        headers_list = self.query_one('#headers_list')

        if headers_list.highlighted is None:
            return

        selected = headers_list.get_option_at_index(headers_list.highlighted)
        if selected:
            del self.state.get_value('headers')[selected.id]
            self.refresh_headers()

    def refresh_headers(self):
        headers_list = self.query_one('#headers_list')
        headers_list.clear_options()
        headers_list.add_options(
            [Option(f'{k}: {v}', id=k) for k, v in self.state.get_value('headers').items()]
        )

    # Global Variables

    @work
    @on(Button.Pressed, '#add_global_variable')
    async def on_add_global_variable_menu_button_message(self, message: Message):
        key, _ = await self.edit_config_state_config_key_value('Add global variable', 'globals')
        if key:
            self.refresh_globals()

    @work
    @on(Button.Pressed, '#edit_global_variable')
    async def on_edit_global_variable_menu_button_message(self, message: Message):
        headers_list = self.query_one('#global_variables')

        if headers_list.highlighted is None:
            return

        selected = headers_list.get_option_at_index(headers_list.highlighted)

        if not selected.id:
            return

        key, _ = await self.edit_config_state_config_key_value('Edit Global Variable', 'globals', orig_key_name=selected.id)

        if not key:
            return

        self.refresh_globals()

    @on(Button.Pressed, '#delete_global_variable')
    def delete_global_variable(self, message: Message):
        headers_list = self.query_one('#global_variables')

        if headers_list.highlighted is None:
            return

        selected = headers_list.get_option_at_index(headers_list.highlighted)
        if selected:
            del self.state.get_value('globals')[selected.id]
            self.refresh_globals()

    def refresh_globals(self):
        globals_list = self.query_one('#global_variables')
        globals_list.clear_options()
        globals_list.add_options(
            [Option(f'{k}: {v}', id=k) for k, v in self.state.get_value('globals').items()]
        )

    # Context Variables
    @work
    @on(Button.Pressed, '#add_context')
    async def on_add_context(self, message: Message):
        name = await self.edit_config_state_config_key(
            'Add Context',
            'contexts',
            default_value=self.state.default_context
        )

        if name:
            self.refresh_contexts()

    @work
    @on(Button.Pressed, '#edit_context')
    async def on_edit_context(self, message: Message):
        orig_name = self.state.context_name

        name = await self.edit_config_state_config_key(
            'Edit Context',
            'contexts',
            orig_key_name=orig_name
        )

        if name:
            self.state.context_name = name
            self.refresh_contexts()

    @on(Button.Pressed, '#delete_context')
    def delete_context(self, message: Message):
        config_list = self.query_one('#contexts_list')
        selected = config_list.value
        if selected:
            self.state.delete_context(selected)
            self.state.context_name = list(self.state.contexts.keys())[0]
            self.refresh_fields()
            self.refresh_contexts()

    def refresh_contexts(self):
        config_list = self.query_one('#contexts_list')
        config_list.set_options([(x, x) for x in self.state.contexts.keys()])
        config_list.value = self.state.context_name


    @work
    @on(Button.Pressed, '#add_context_variable')
    async def on_add_context_variable_menu_button_message(self, message: Message):
        key, _ = await self.edit_config_state_config_key_value('Add context variable', 'context_variables')
        if key:
            self.refresh_context_variables()

    @work
    @on(Button.Pressed, '#edit_context_variable')
    async def on_edit_context_variable_menu_button_message(self, message: Message):
        headers_list = self.query_one('#context_variables')

        if headers_list.highlighted is None:
            return

        selected = headers_list.get_option_at_index(headers_list.highlighted)

        if not selected.id:
            return

        key, _ = await self.edit_config_state_config_key_value(
            'Edit context Variable',
            'context_variables',
            orig_key_name=selected.id
        )

        if not key:
            return

        self.refresh_context_variables()

    @on(Button.Pressed, '#delete_context_variable')
    def delete_context_variable(self, message: Message):
        headers_list = self.query_one('#context_variables')

        if headers_list.highlighted is None:
            return

        selected = headers_list.get_option_at_index(headers_list.highlighted)
        if selected:
            del self.state.get_value('context_variables')[selected.id]
            self.refresh_context_variables()

    def refresh_context_variables(self):
        globals_list = self.query_one('#context_variables')
        globals_list.clear_options()
        globals_list.add_options(
            [Option(f'{k}: {v}', id=k) for k, v in self.state.get_value('context_variables').items()]
        )

    # Texts

    @work
    @on(Button.Pressed, '#add_text')
    async def on_add_text_select_item(self, message: Message):
        if not self.state.get_value('texts'):
            self.state.set_value('texts', {})

        await self.edit_config_state_config_key('Add Text', 'texts')

        self.refresh_texts()

    @work
    @on(Button.Pressed, '#edit_text')
    async def on_edit_edit_text_select_item(self, message: Message):
        config_list = self.query_one('#texts')
        selected = config_list.value

        if selected is None:
            return

        new_name = await self.edit_config_state_config_key('Edit Text', 'texts', orig_key_name=selected)

        if not new_name:
            return

        self.state.set_value('text_selected', new_name)

        self.refresh_texts()

    @on(Button.Pressed, '#delete_text')
    def delete_text(self, message: Message):
        texts_list = self.query_one('#texts')

        selected = texts_list.value

        if selected is None:
            return

        self.state.get_value('texts').pop(selected.id)

        self.refresh_texts()

    def refresh_texts(self):
        text_list = self.query_one('#texts')
        values = [(x, x) for x in self.state.get_value('texts', {'': ''}).keys()]
        text_list.set_options(values)
        text_list.value = self.state.get_value('text_selected', values[0][0])

    # Configurations

    @work
    @on(Button.Pressed, '#add_configuration')
    async def on_add_configuration(self, message: Message):
        name = await self.edit_config_state_config_key(
            'Add Configuration',
            'configurations',
            default_value=self.state.default_configuration
        )

        if name:
            self.refresh_configurations()

    @work
    @on(Button.Pressed, '#edit_configuration')
    async def on_edit_configuration(self, message: Message):
        orig_name = self.state.configuration_name

        name = await self.edit_config_state_config_key(
            'Edit Configuration',
            'configurations',
            orig_key_name=orig_name
        )

        if name:
            self.state.configuration_name = name
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

    def refresh_configurations(self):
        config_list = self.query_one('#configurations_list')
        config_list.set_options([(x, x) for x in self.state.configurations.keys()])
        config_list.value = self.state.configuration_name

    def on_mount(self):
        self.refresh_fields()
        self.refresh_configurations()
        self.refresh_texts()

    @on(Button.Pressed, '#connect')
    async def on_connect_button_message(self, message: Message):
        log = self.query_one('#ws_sessions_log')
        addr = self.query_one(AddressInput).value

        if self.state.get_value('template_url'):
            vars = self.state.get_variables()
            addr = render_template(addr, self.state.get_variables())

        if self._connect_task:
            button = self.query_one('#connect')
            button.label = 'Connect'

            self._connect_task.cancel()
            self._ws = None

        if self._connecting_params:
            self._connecting_params = None
            return

        button = self.query_one('#connect')
        button.label = 'Disconnect'
        self._connecting_params = {
            'url': addr,
            'headers': self.state.get_value('headers'),
            'autoping': self.state.get_value('autoping'),
            'ssl_check': self.state.get_value('ssl_check')
        }

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

                if self.state.get_value('template_data'):
                    text = render_template(text, self.state.get_variables())

                await self._ws.send_str(text)
                log.write(f'[yellow]Sent: {text}')
            except Exception as exc:
                log.write(f'[red]Error: {exc}')

    async def get_key_from_modal(self, title: str, name: str = None) -> str:
        screen = EditNameModalScreen(title, name=name)

        data = await self.push_screen_wait(
            screen
        )

        return data

    async def get_key_value_from_modal(self, title: str, name: str = None, value: str = None) -> str:
        screen = EditNameValueScreen(title, name=name, value=value)

        data = await self.push_screen_wait(
            screen
        )

        if not data:
            return (None, None)

        return (data[0], data[1])

    async def edit_config_state_config_key(
            self,
            modal_title: str,
            section: str,
            orig_key_name: str = None,
            default_value: str = ''
        ) -> None|str:

        data = await self.get_key_from_modal(modal_title, name=orig_key_name)

        if data is None:
            return

        if orig_key_name is None:
            if self.state.get_value(section) and data in self.state.get_value(section):
                # unable to create as record already exists
                return
            self.state.get_value(section)[data] = default_value
            return data

        if orig_key_name and data == orig_key_name:
            return data

        if (orig_key_name and
            orig_key_name != data and
            self.state.get_value(section) and
            data in self.state.get_value(section)
        ):
            # unable to rename as record already exists
            return

        self.state.get_value(section)[data] = self.state.get_value(section).pop(orig_key_name)
        return data

    async def edit_config_state_config_key_value(
            self,
            modal_title: str,
            section: str,
            orig_key_name: str = None
        ) -> None|str:

        value = ''
        if orig_key_name:
            value = self.state.get_value(section).get(orig_key_name, '')

        key, value = await self.get_key_value_from_modal(modal_title, name=orig_key_name, value=value)

        if key is None:
            return (None, None)

        if orig_key_name is None:
            if self.state.get_value(section) and key in self.state.get_value(section):
                # unable to create as record already exists
                return (None, None)
            self.state.get_value(section)[key] = value
            return (key, value)

        if (orig_key_name and
            orig_key_name != key and
            self.state.get_value(section) and
            key in self.state.get_value(section)
        ):
            # unable to rename as record already exists
            return (None, None)

        self.state.get_value(section).pop(orig_key_name)
        self.state.get_value(section)[key] = value
        return (key, value)

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

    @on(Switch.Changed, '#autoping')
    def autoping_switch(self, message: Message):
        self.state.set_value('autoping', message.value)

    @on(AddressInput.Changed, '#address')
    def address_switch(self, message: Message):
        self.state.set_value('url', message.value)

    @on(Switch.Changed, '#auto_reconnect')
    def auto_reconnect_switch(self, message: Message):
        self.state.set_value('auto_reconnect', message.value)

    @on(Switch.Changed, '#ssl_check')
    def ssl_check_switch(self, message: Message):
        self.state.set_value('ssl_check', message.value)

    @on(Switch.Changed, '#template_url')
    def template_url_switch(self, message: Message):
        self.state.set_value('template_url', message.value)

    @on(Switch.Changed, '#template_data')
    def template_data_switch(self, message: Message):
        self.state.set_value('template_data', message.value)

    @on(Select.Changed, '#contexts_list')
    def change_context(self, message: Message):
        selected = message.value

        if selected:
            self.state.context_name = selected
            self.refresh_context_variables()

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
        yield ScrollableContainer(
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
            HorizontalHAuto(
                Label('\nUse Temlate for the url:'),
                Switch(self.state.get_value('template_url'), animate=True, id='template_url')
            ),
            HorizontalHAuto(
                Label('\nUse templates for the data being sent.:'),
                Switch(self.state.get_value('template_data'), animate=True, id='template_data')
            ),
            Label('Configurations'),
            HorizontalHAuto(
                Select([('', '')], id='configurations_list'),
                Button('Add', id='add_configuration'),
                Button('Delete', id='delete_configuration'),
                Button('Edit', id='edit_configuration'),
            ),
            Label('Contexts'),
            HorizontalHAuto(
                Select([('', '')], id='contexts_list'),
                Button('Add', id='add_context'),
                Button('Delete', id='delete_context'),
                Button('Edit', id='edit_context'),
            ),
            Label('Context Variables (overrides global variables)'),
            HorizontalHAuto(
                OptionList(id='context_variables'),
                Button('Add', id='add_context_variable'),
                Button('Delete', id='delete_context_variable'),
                Button('Edit', id='edit_context_variable'),
            ),
            Label('Global Variables'),
            HorizontalHAuto(
                OptionList(id='global_variables'),
                Button('Add', id='add_global_variable'),
                Button('Delete', id='delete_global_variable'),
                Button('Edit', id='edit_global_variable'),
            ),
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