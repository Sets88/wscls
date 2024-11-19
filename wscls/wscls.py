import argparse
import os
import asyncio
import json
import shutil
from copy import deepcopy
from time import time
from typing import Any
import tempfile
from string import Template
from collections import namedtuple

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
from textual.widgets._select import SelectCurrent
from textual.widgets._select import SelectOverlay
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
import pyperclip


HTTP_METHODS = [
    'WS', 'GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD'
]


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
        grid-rows: 4 1 5fr 3 30%
    }
    """


class ConnectContainer(Widget):
    DEFAULT_CSS = """
    ConnectContainer {
        width: 1fr;
        height: auto;
        layout: grid;
        grid-columns: 1fr 15 15;
        grid-size-columns: 3;
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


class SwitchContainer(Widget):
    DEFAULT_CSS = """
    SwitchContainer {
        width: 50;
        height: auto;
        layout: grid;
        grid-columns: 2fr 15;
        grid-size-columns: 2;
    }
    """


class NarrowButton(Button):
    DEFAULT_CSS = """
    NarrowButton {
        min-width: 8;
    }
    """


def render_template(template: str, variables: dict) -> str:
    return Template(template).safe_substitute(variables)


class WidgetImprovements(Widget):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._last_click_ts = None

    def on_click(self, event: Event):
        """Double click - copy to clipboard"""

        if hasattr(super(), 'on_click'):
            super().on_click(event)

        if self._last_click_ts is None:
            self._last_click_ts = time()
            return

        if time() - self._last_click_ts > 0.5:
            self._last_click_ts = time()
            return

        self.on_double_click(event)

    def on_double_click(self, event: Event):
        pass


class SelectSearchable(Select):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._search_str = ''

    def on_key(self, event: Event):
        if self._search_str == self.value:
            self._search_str = ''

        if event.is_printable:
            self._search_str += event.character
        elif event.key == 'backspace':
            self._search_str = self._search_str[:-1]
        else:
            return

        self.query_one(SelectCurrent).update(self._search_str)

        options_list = self.query_one(SelectOverlay)

        for idx, (key, val) in enumerate(self._options):
            options_list.enable_option_at_index(idx)

            if val and self._search_str.lower() not in val.lower():
                options_list.disable_option_at_index(idx)

    def _watch_expanded(self, expanded: bool) -> None:
        super()._watch_expanded(expanded=expanded)
        self._search_str = self.value
        self.query_one(SelectCurrent).update(self._search_str)

        if not expanded:
            for idx in range(len(self._options)):
                self.query_one(SelectOverlay).enable_option_at_index(idx)


class State:
    def __init__(self, filename: str = None):
        if not filename:
            filename = os.path.join(os.path.expanduser("~"), '.wscls.json')
        self.configuration_name = 'default'
        self.files_mtime = {}
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
            'filename': '',
            'url': '',
            'method': 'WS',
            'headers': {},
            'autoping': False,
            'texts': {'': self.default_text},
            'auto_reconnect': True,
            'ssl_check': True,
            'show_headers': False,
            'follow_redirects': True,
            'stick_url_to_text': False
        }

    @property
    def default_text(self):
        return {
            'text': '',
            'url': '',
            'method': 'WS'
        }

    def get_configuration(self):
        try:
            return self.configurations[self.configuration_name]
        except KeyError:
            self.configuration_name = list(self.configurations.keys())[0]
            return self.configurations[self.configuration_name]

    def export_configuration(self, name, filename):
        try:
            with open(filename, 'w') as fil:
                config = deepcopy(self.configurations[name])
                config.pop('filename', None)
                json.dump(config, fil)
            return False
        except Exception as exc:
            return str(exc)

    def load_configuration_from_file(self, app, name, filename):
        config = self.configurations.get(name, self.default_configuration)

        try:
            with open(filename, 'r', encoding='utf8') as config_filename:
                self.files_mtime[filename] = os.path.getmtime(filename)
                config.update(json.load(config_filename))
                config['filename'] = filename
        except Exception as exc:
            app.notify(
                f'Error loading configuration from file: {exc}',
                title='Error',
                severity='error'
            )
        self.configurations[name] = config


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

    def get_current_text(self):
        if not self.get_value('texts'):
            self.set_value('texts', self.default_text)
        if self.get_value('text_selected') not in self.get_value('texts'):
            self.set_value('text_selected', list(self.get_value('texts').keys())[0])

        current_text = self.get_value('texts').get(self.get_value('text_selected'))

        if isinstance(current_text, str):
            current_text = {'text': current_text, 'url': ''}
            self.get_value('texts')[self.get_value('text_selected')] = current_text
        return current_text

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

    def load(self, app):
        if not os.path.exists(self.state_filename):
            self.loaded = True
            return
        try:
            with open(self.state_filename, 'r', encoding='utf8') as fil:
                self.files_mtime[self.state_filename] = os.path.getmtime(self.state_filename)
                state_file = json.load(fil)
                self.globals = state_file.get('globals', self.globals)
                self.configuration_name = state_file.get('selected_configuration', 'default')
                self.contexts = state_file.get('contexts', self.contexts)
                self.context_name = state_file.get('selected_context', 'default')
                self.loaded = True

                for key, config in state_file.get('configurations', self.configurations).items():
                    if config.get('filename'):
                        self.load_configuration_from_file(app, key, config['filename'])
                        continue

                    self.configurations[key] = config

        except Exception as exc:
            app.notify(f'Error loading state: {exc}', title='Error', severity='error')

    async def save(self, app):
        new_configurations = {}
        state_data = {
            'selected_configuration': self.configuration_name,
            'globals': self.globals,
            'contexts': self.contexts,
            'selected_context': self.context_name

        }

        if not self.loaded:
            return

        for key, config in self.configurations.items():
            if config.get('filename'):
                try:
                    config_to_save = deepcopy(config)
                    config_to_save.pop('filename', None)

                    if self.files_mtime.get(config['filename']) != os.path.getmtime(config['filename']):
                        result = await app.confirm_request(
                            f'File "{config["filename"]}" has been modified. Do you want to overwrite it?',
                            with_no_button=True
                        )

                        if result is None:
                            return

                        if not result:
                            continue

                    with tempfile.NamedTemporaryFile(mode="w", buffering=1) as fil:
                        fil.write(json.dumps(config_to_save, indent=2))
                        fil.flush()

                        shutil.copy(fil.name, config['filename'])
                except Exception as exc:
                    print(exc)

                new_configurations[key] = {
                    'filename': config['filename'],
                }
                continue

            new_configurations[key] = config

        state_data['configurations'] = new_configurations

        if self.files_mtime.get(self.state_filename) != os.path.getmtime(self.state_filename):
            result = await app.confirm_request(
                f'File "{self.state_filename}" has been modified. Do you want to overwrite it?',
                with_no_button=True
            )

            if result is None:
                return

            if not result:
                return True

        with tempfile.NamedTemporaryFile(mode="w", buffering=1) as fil:
            fil.write(json.dumps(state_data))
            fil.flush()
            shutil.copy(fil.name, self.state_filename)

        return True


class WsRichLog(RichLog, WidgetImprovements):
    BINDINGS = [
        Binding('s', 'toggle_scroll', 'Toggle auto scroll'),
        Binding('c', 'clear', 'Clear log'),
        Binding('w', 'toggle_wrap', 'Toggle word wrap'),
    ]

    def on_double_click(self, event: Event):
        for line in self.lines[int(self.scroll_y) + event.y-1:]:
            pyperclip.copy(line.text)
            self.app.notify(f'Copied to clipboard', title='Copied', severity='info')
            break

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


class SingleInputModalScreen(ModalScreen):
    CSS = """
        SingleInputModalScreen {
            align: center middle;
        }
        SingleInputModalScreen > Vertical {
            background: #101030;
            border: tall #303040;
            height: 12;
            width: 70;
        }
        SingleInputModalScreen #content {
            margin: 0 1;
        }
        SingleInputModalScreen Label {
            margin: 0 1;
        }
        SingleInputModalScreen #buttons {
            margin: 0 1;
            align: center bottom;
        }
    """
    def __init__(self, title, input1=None, input_placeholder='Name') -> None:
        self.input1 = input1
        self.modal_title = title
        self.input_placeholder = input_placeholder
        self.result_type = namedtuple('SingleInputResult', ['input1'])
        super().__init__()

    @on(Button.Pressed, '#add')
    def add(self, message: Message):
        self.dismiss(self.result_type(self.query_one('#text_name').value))

    @on(Button.Pressed, '#save')
    def save(self, message: Message):
        self.dismiss(self.result_type(self.query_one('#text_name').value))

    @on(Button.Pressed, '#cancel')
    def cancel(self, message: Message):
        self.dismiss(None)

    @on(Input.Submitted)
    def submit(self, message: Message):
        self.dismiss(self.result_type(self.query_one('#text_name').value))

    def on_key(self, event: Event):
        if event.key == 'escape':
            self.dismiss(None)

    def compose(self) -> ComposeResult:
        with Vertical():
            with Vertical(id='content'):
                yield Label(self.modal_title)
                yield Input(placeholder=self.input_placeholder, id='text_name', value=self.input1)

                if self.input1:
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


class DoubleInputModalScreen(ModalScreen):
    CSS = """
        DoubleInputModalScreen {
            align: center middle;
        }
        DoubleInputModalScreen > Vertical {
            background: #101030;
            border: tall #303040;
            height: 12;
            width: 70;
        }
        DoubleInputModalScreen #content {
            margin: 0 1;
        }
        DoubleInputModalScreen Label {
            margin: 0 1;
        }
        DoubleInputModalScreen #buttons {
            margin: 0 1;
            align: center bottom;
        }
    """
    def __init__(self,
            title,
            input1=None,
            input2=None,
            input1_placeholder = 'Name',
            input2_placeholder = 'Value'
        ) -> None:
        self.input1 = input1
        self.input2 = input2
        self.modal_title = title
        self.input1_placeholder = input1_placeholder
        self.input2_placeholder = input2_placeholder
        self.result_type = namedtuple('DoubleInputResult', ['input1', 'input2'])
        super().__init__()

    @on(Button.Pressed, '#add')
    def add(self, message: Message):
        self.dismiss(
            self.result_type(self.query_one('#imput_name').value, self.query_one('#input_value').value)
        )

    @on(Button.Pressed, '#save')
    def save(self, message: Message):
        self.dismiss(
            self.result_type(self.query_one('#imput_name').value, self.query_one('#input_value').value)
        )

    @on(Button.Pressed, '#cancel')
    def cancel(self, message: Message):
        self.dismiss(None)

    @on(Input.Submitted)
    def submit(self, message: Message):
        self.dismiss(
            self.result_type(self.query_one('#imput_name').value, self.query_one('#input_value').value)
        )

    def on_key(self, event: Event):
        if event.key == 'escape':
            self.dismiss(None)

    def compose(self) -> ComposeResult:
        with Vertical():
            with Vertical(id='content'):
                yield Label(self.modal_title)
                yield Input(placeholder=self.input1_placeholder, id='imput_name', value=self.input1)
                yield Input(placeholder=self.input2_placeholder, id='input_value', value=self.input2)

                if self.input1:
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


class ConfirmScreen(ModalScreen):
    CSS = """
        ConfirmScreen {
            align: center middle;
        }
        ConfirmScreen > Vertical {
            background: #101030;
            border: tall #303040;
            height: 10;
            width: 70;
        }
        ConfirmScreen #content {
            margin: 0 1;
        }
        ConfirmScreen Label {
            padding: 1 2;
            height: 100%;
            width: 100%;
            color: auto;
            text-align: center;
        }
        ConfirmScreen #buttons {
            margin: 0 1;
            align: center bottom;
        }
    """
    def __init__(self, title, name=None, with_no_button=False) -> None:
        self.key_name = name
        self.modal_title = title
        self.with_no_button = with_no_button
        super().__init__()

    @on(Button.Pressed, '#confirm')
    def confirm(self, message: Message):
        self.dismiss(True)

    @on(Button.Pressed, '#cancel')
    def cancel(self, message: Message):
        self.dismiss(None)

    @on(Button.Pressed, '#no')
    def no(self, message: Message):
        self.dismiss(False)

    @on(Input.Submitted)
    def submit(self, message: Message):
        self.dismiss(True)

    def on_key(self, event: Event):
        if event.key == 'escape':
            self.dismiss(None)

    def compose(self) -> ComposeResult:
        with Vertical():
            with Vertical(id='content'):
                yield Horizontal(
                    Label(self.modal_title)
                )
                with Horizontal(id='buttons'):
                    yield Button('Yes', id='confirm')
                    if self.with_no_button:
                        yield Button('No', id='no')
                    yield Button('Cancel', id='cancel')


class AddressInput(Input, WidgetImprovements):
    def on_double_click(self, event: Event):
        pyperclip.copy(self.value)
        self.app.notify(f'Copied to clipboard', title='Copied', severity='info')


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


class SendTextArea(TextArea, WidgetImprovements):
    BINDINGS = [
        Binding('ctrl+r', 'send_message'),
        Binding('ctrl+f', 'send_message')
    ]
    def on_text_area_changed(self, event: Event):
        self.app.state.get_current_text()['text'] = self.text

    def on_double_click(self, event: Event):
        pyperclip.copy(self.text)
        self.app.notify(f'Copied to clipboard', title='Copied', severity='info')

    async def action_send_message(self):
        self.app.query_one('#send_message').action_press()


class WsApp(App):
    def __init__(self, state):
        super().__init__()
        self._connect_task = None
        self._ws = None
        self._connecting_params = None
        self.state = state
        self.status_label = None
        self.log_field = None

    @work
    async def action_quit(self):
        save_result = await self.state.save(self)
        if save_result:
            self.exit()

    async def process_incomming_ws_message(self, msg: WSMessage):
        if msg.type == aiohttp.WSMsgType.ERROR:
            self.log_field.write('[red]Error: ')
        elif msg.type == aiohttp.WSMsgType.PONG:
            rtt = round((time() - float(msg.data.decode('utf-8'))) * 1000, 3)
            self.log_field.write(f'[cyan]Pong received, RTT: {rtt} ms')
        else:
            self.log_field.write(f'[cyan]Received:\n{msg.data}')

    def on_connected(self, url: str):
        text = f'[green]Connected to: {url}'
        self.log_field.write(text)
        self.set_status_text(text)
        self.log_field.styles.border = ('heavy', 'green')

    def on_disconnected(self):
        text = '[red]Disconnected'
        self.set_status_text(text)
        self.log_field.write(text)
        self.log_field.styles.border = ('heavy', 'red')

    async def connect_ws(self, session: aiohttp.ClientSession):
        ssl_check = None if self._connecting_params['ssl_check'] else False
        url = self._connecting_params['url']
        headers = self._connecting_params['headers']
        autoping = self._connecting_params['autoping']

        async with session.ws_connect(
            url,
            headers=headers,
            autoping=autoping,
            ssl=ssl_check
        ) as ws:
            try:
                self._ws = ws
                self.on_connected(url)
                async for msg in ws:
                    await self.process_incomming_ws_message(msg)

                self.log_field.write(f'[red]Closed by remote side with code: {ws.close_code}')
            except Exception as exc:
                self.log_field.write(f'[red]Error: {exc}')
            finally:
                self.on_disconnected()

    async def connect_http(self, session: aiohttp.ClientSession):
        self.log_field.styles.border = ('heavy', 'black')
        url = self._connecting_params['url']
        method = self._connecting_params['method']
        headers = self._connecting_params['headers']
        ssl_check = None if self._connecting_params['ssl_check'] else False

        follow_redirects = self.state.get_value('follow_redirects')

        textar = self.query_one(SendTextArea)
        if textar.selected_text:
            text = textar.selected_text
        else:
            text = textar.text

        if self.state.get_value('template_data'):
            text = render_template(text, self.state.get_variables())

        async with session.request(
            method,
            url,
            headers=headers,
            ssl=ssl_check,
            data=text,
            allow_redirects=follow_redirects
        ) as resp:
            self.log_field.write(f'[cyan]Request: {method} {url}')
            self.log_field.write(f'[cyan]Response: {resp.status}')
            if self.state.get_value('show_headers'):
                headers_text = ('\n   ').join([f"{key}: {value}" for key, value in resp.headers.items()])
                self.log_field.write(f'[cyan]Headers:\n   {headers_text}')
            self.log_field.write(f'[cyan]Body: \n{await resp.text()}')

    async def connect(self):
        while True:
            if not self._connecting_params:
                break

            try:
                async with aiohttp.ClientSession(raise_for_status=True) as session:
                    if self._connecting_params['method'] == 'WS':
                        await self.connect_ws(session)
                    else:
                        await self.connect_http(session)
            except Exception as exc:
                self.log_field.write(f'[red]Error: {exc}')

            if not self.state.get_value('auto_reconnect') or self._connecting_params['method'] != 'WS':
                button = self.query_one('#connect')
                button.label = 'Connect'

                self._connecting_params = None

                break

            await asyncio.sleep(1)
            if not self._connecting_params:
                break

            self.log_field.write(f'[yellow]Reconnecting to: {self._connecting_params["url"]}')

    def refresh_fields(self):
        self.query_one(AddressInput).value = self.state.get_value('url')

        self.query_one(SendTextArea).text = (
            self.state.get_current_text()['text']
        )

        self.query_one('#autoping').value = self.state.get_value('autoping')
        self.query_one('#show_headers').value = self.state.get_value('show_headers')
        self.query_one('#stick_url_to_text').value = self.state.get_value('stick_url_to_text')
        self.query_one('#follow_redirects').value = self.state.get_value('follow_redirects')
        self.query_one('#method').value = self.state.get_value('method', 'WS')
        self.query_one('#auto_reconnect').value = self.state.get_value('auto_reconnect')
        self.query_one('#ssl_check').value = self.state.get_value('ssl_check')
        self.query_one('#template_url').value = self.state.get_value('template_url')
        self.query_one('#template_headers').value = self.state.get_value('template_headers')
        self.query_one('#template_data').value = self.state.get_value('template_data')
        self.refresh_headers()
        self.refresh_globals()
        self.refresh_contexts()
        self.refresh_context_variables()

    # Headers

    @work
    @on(Button.Pressed, '#add_header')
    async def on_add_header_menu_button_message(self, message: Message):
        val = await self.edit_config_state_config_key_value(
            'headers',
            modal=DoubleInputModalScreen('Add Header')
        )
        if not val:
            return

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

        input1 = selected.id
        input2 = self.state.get_value('headers').get(input1, '')

        val = await self.edit_config_state_config_key_value(
            'headers',
            modal=DoubleInputModalScreen('Edit Header', input1=input1, input2=input2),
            orig_key_name=selected.id
        )

        if not val:
            return

        self.refresh_headers()

    @work
    @on(Button.Pressed, '#delete_header')
    async def delete_header(self, message: Message):
        headers_list = self.query_one('#headers_list')

        if headers_list.highlighted is None:
            return

        selected = headers_list.get_option_at_index(headers_list.highlighted)

        if not selected:
            return

        if not await self.confirm_request(f'Are you sure you want to delete header "{selected.id}" ?'):
            return

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
        val= await self.edit_config_state_config_key_value(
            'globals',
            modal=DoubleInputModalScreen('Add Global Variable')
        )
        if not val:
            return

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

        input1 = selected.id
        input2 = self.state.get_value('globals').get(input1, '')

        val = await self.edit_config_state_config_key_value(
            'globals',
            modal=DoubleInputModalScreen('Edit Global Variable', input1=input1, input2=input2),
            orig_key_name=selected.id
        )

        if not val:
            return

        self.refresh_globals()

    @work
    @on(Button.Pressed, '#delete_global_variable')
    async def delete_global_variable(self, message: Message):
        headers_list = self.query_one('#global_variables')

        if headers_list.highlighted is None:
            return

        selected = headers_list.get_option_at_index(headers_list.highlighted)

        if not selected:
            return

        if not await self.confirm_request(f'Are you sure you want to delete global variable "{selected.id}"?'):
            return

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
        val = await self.edit_config_state_config_key(
            'contexts',
            modal=SingleInputModalScreen('Add Context'),
            default_value=self.state.default_context
        )

        if not val:
            return

        self.refresh_contexts()

    @work
    @on(Button.Pressed, '#edit_context')
    async def on_edit_context(self, message: Message):
        orig_name = self.state.context_name

        val = await self.edit_config_state_config_key(
            'contexts',
            modal=SingleInputModalScreen('Edit Context', input1=orig_name),
            orig_key_name=orig_name
        )

        if not val:
            return

        self.state.context_name = val.input1
        self.refresh_contexts()

    @work
    @on(Button.Pressed, '#delete_context')
    async def delete_context(self, message: Message):
        config_list = self.query_one('#contexts_list')
        selected = config_list.value

        if not selected:
            return

        if not await self.confirm_request(f'Are you sure you want to delete context "{selected}"?'):
            return


        self.state.delete_context(selected)
        self.state.context_name = list(self.state.contexts.keys())[0]
        self.refresh_fields()
        self.refresh_contexts()

    def refresh_contexts(self):
        config_list = self.query_one('#contexts_list')
        config_list.set_options([(x, x) for x in sorted(self.state.contexts.keys())])
        config_list.value = self.state.context_name


    @work
    @on(Button.Pressed, '#add_context_variable')
    async def on_add_context_variable_menu_button_message(self, message: Message):
        val = await self.edit_config_state_config_key_value(
            'context_variables',
            modal=DoubleInputModalScreen('Add Context Variable')
        )
        if not val:
            return

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

        input1 = selected.id
        input2 = self.state.get_value('context_variables').get(input1, '')

        val = await self.edit_config_state_config_key_value(
            'context_variables',
            modal=DoubleInputModalScreen('Edit Context Variable', input1=input1, input2=input2),
            orig_key_name=selected.id
        )

        if not val:
            return

        self.refresh_context_variables()

    @work
    @on(Button.Pressed, '#delete_context_variable')
    async def delete_context_variable(self, message: Message):
        headers_list = self.query_one('#context_variables')

        if headers_list.highlighted is None:
            return

        selected = headers_list.get_option_at_index(headers_list.highlighted)
        if not selected:
            return

        if not await self.confirm_request(f'Are you sure you want to delete context variable "{selected.id}"?'):
            return

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
        val = await self.edit_config_state_config_key(
            'texts',
            modal=SingleInputModalScreen('Add Text'),
            default_value=self.state.default_text
        )

        if not val:
            return

        self.refresh_texts()

    @work
    @on(Button.Pressed, '#edit_text')
    async def on_edit_edit_text_select_item(self, message: Message):
        config_list = self.query_one('#texts')
        selected = config_list.value

        if selected is None:
            return

        val = await self.edit_config_state_config_key(
            'texts',
            modal=SingleInputModalScreen('Edit Text', input1=selected),
            orig_key_name=selected
        )

        if not val:
            return

        self.state.set_value('text_selected', val.input1)

        self.refresh_texts()

    @work
    @on(Button.Pressed, '#delete_text')
    async def delete_text(self, message: Message):
        texts_list = self.query_one('#texts')

        selected = texts_list.value

        if selected is None:
            return

        if not await self.confirm_request(f'Are you sure you want to delete text "{selected}"?'):
            return

        self.state.get_value('texts').pop(selected)

        self.state.get_current_text()

        self.refresh_texts()

    @on(Button.Pressed, '#copy_curl')
    async def copy_curl(self, message: Message):
        params = self.get_connect_params()

        if params['method'] == 'WS':
            return

        curl_template = 'curl -X {method} {url} {headers} {data}'

        curl = curl_template.format(
            method=params['method'],
            url=params['url'],
            headers=' '.join([f'-H "{k}: {v}"' for k, v in params['headers'].items()]),
            data=self.state.get_current_text()['text']
        )

        pyperclip.copy(curl)
        self.app.notify(f'Copied to clipboard', title='Copied', severity='info')

    def refresh_texts(self):
        text_list = self.query_one('#texts')
        values = [(x, x) for x in sorted(self.state.get_value('texts').keys())]
        text_list.set_options(values)
        text_list.value = self.state.get_value('text_selected', values[0][0])

    # Configurations

    @work
    @on(Button.Pressed, '#add_configuration')
    async def on_add_configuration(self, message: Message):
        modal = DoubleInputModalScreen(
            'Add Configuration',
            input1_placeholder='Name',
            input2_placeholder='External filename (optional)'
        )

        value = self.state.default_configuration

        val = await self.edit_config_state_config_key(
            'configurations',
            modal=modal,
            default_value=value,
        )

        if not val:
            return

        if val.input2:
            self.state.load_configuration_from_file(self, val.input1, val.input2)

        self.refresh_configurations()

    @work
    @on(Button.Pressed, '#edit_configuration')
    async def on_edit_configuration(self, message: Message):
        orig_name = self.state.configuration_name

        input2 = self.state.get_value('configurations').get(orig_name, {}).get('filename', '')

        modal = DoubleInputModalScreen(
            'Edit Configuration',
            input1=orig_name,
            input2=input2,
            input1_placeholder='Name',
            input2_placeholder='Outsource filename (optional)'
        )

        val = await self.edit_config_state_config_key(
            'configurations',
            modal=modal,
            orig_key_name=orig_name
        )

        if not val:
            return

        if val.input2:
            if input2 != val.input2 and os.path.exists(input2):
                if not await self.confirm_request(
                    f'File "{val.input2}" already exists. Are you sure you want to update filename?'
                ):
                    return

            self.state.get_value('configurations')[val.input1]['filename'] = val.input2

        self.state.configuration_name = val.input1
        self.refresh_configurations()

    @work
    @on(Button.Pressed, '#export_configuration')
    async def on_export_configuration(self, message: Message):
        config_name = self.state.configuration_name

        modal = SingleInputModalScreen(
            'Export Configuration',
            input_placeholder='Filename to export to',
        )

        val = await self.push_screen_wait(
            modal
        )

        if not val:
            return

        if os.path.exists(val.input1):
            if not await self.confirm_request(f'File "{val.input1}" already exists. Overwrite?'):
                return

        export_err = self.state.export_configuration(config_name, val.input1)

        if not export_err:
            self.notify(f'Configuration "{config_name}" exported to "{val.input1}"', title='Exported')
        else:
            self.notify(
                f'Error exporting configuration "{config_name}" to "{val.input1}" {export_err}',
                title='Error',
                severity='error'
            )

    @work
    @on(Button.Pressed, '#delete_configuration')
    async def delete_configuration(self, message: Message):
        config_list = self.query_one('#configurations_list')
        selected = config_list.value
        if not selected:
            return

        if not await self.confirm_request(f'Are you sure you want to delete configuration "{selected}"?'):
            return

        self.state.delete_configuration(selected)
        self.state.configuration_name = list(self.state.configurations.keys())[0]
        self.refresh_fields()
        self.refresh_configurations()

    def refresh_configurations(self):
        config_list = self.query_one('#configurations_list')
        config_list.set_options([(x, x) for x in sorted(self.state.configurations.keys())])
        config_list.value = self.state.configuration_name

    def on_mount(self):
        self.state.load(self)
        self.refresh_fields()
        self.refresh_configurations()
        self.refresh_texts()

    def get_connect_params(self):
        addr = self.query_one(AddressInput).value

        if self.state.get_value('template_url'):
            addr = render_template(addr, self.state.get_variables())

        headers = {}

        for key, value in self.state.get_value('headers').items():
            if self.state.get_value('template_headers'):
                key = render_template(key, self.state.get_variables())
                value = render_template(value, self.state.get_variables())

            headers[key] = value

        return {
            'url': addr,
            'headers': headers,
            'autoping': self.state.get_value('autoping'),
            'ssl_check': self.state.get_value('ssl_check'),
            'method': self.state.get_value('method', 'WS'),
            'follow_redirects': self.state.get_value('follow_redirects')
        }

    @on(Button.Pressed, '#connect')
    async def on_connect_button_message(self, message: Message):

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
        self._connecting_params = self.get_connect_params()

        self.log_field.write(f'Connecting to: {self._connecting_params["url"]}')

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
                log.write(f'[yellow]Sent:\n{text}')
            except Exception as exc:
                log.write(f'[red]Error: {exc}')

        if self.state.get_value('method') != 'WS':
            self.query_one('#connect').action_press()

    async def edit_config_state_config_key(
            self,
            section: str,
            modal = None,
            orig_key_name: str = None,
            default_value: str = ''
        ) -> None|str:

        data = await self.push_screen_wait(
            modal
        )

        if data is None:
            return

        if orig_key_name is None:
            if self.state.get_value(section) and data.input1 in self.state.get_value(section):
                # unable to create as record already exists
                return
            self.state.get_value(section)[data.input1] = default_value
            return data

        if orig_key_name and data.input1 == orig_key_name:
            return data

        if (orig_key_name and
            orig_key_name != data.input1 and
            self.state.get_value(section) and
            data.input1 in self.state.get_value(section)
        ):
            # unable to rename as record already exists
            return

        self.state.get_value(section)[data.input1] = self.state.get_value(section).pop(orig_key_name)
        return data

    async def confirm_request(self, title: str, with_no_button=None) -> bool:
        screen = ConfirmScreen(title, with_no_button=with_no_button)

        data = await self.push_screen_wait(
            screen
        )

        return data

    async def edit_config_state_config_key_value(
            self,
            section: str,
            modal = None,
            orig_key_name: str = None
        ) -> None|str:

        value = ''
        if orig_key_name:
            value = self.state.get_value(section).get(orig_key_name, '')

        val = await self.push_screen_wait(
            modal
        )

        if not val:
            return None

        if orig_key_name is None:
            if self.state.get_value(section) and val.input1 in self.state.get_value(section):
                # unable to create as record already exists
                return (None, None)
            self.state.get_value(section)[val.input1] = val.input2
            return val

        if (orig_key_name and
            orig_key_name != val.input1 and
            self.state.get_value(section) and
            val.input1 in self.state.get_value(section)
        ):
            # unable to rename as record already exists
            return val

        self.state.get_value(section).pop(orig_key_name)
        self.state.get_value(section)[val.input1] = val.input2
        return val

    @on(Button.Pressed, '#ping')
    async def ping(self):
        log = self.query_one('#ws_sessions_log')
        if self._ws:
            try:
                await self._ws.ping(str(time()))
                log.write('[yellow]Ping sent')
            except Exception as exc:
                log.write(f'[red]Error: {exc}')

    @on(Switch.Changed, '#show_headers')
    def show_headers_switch(self, message: Message):
        self.state.set_value('show_headers', message.value)

    @on(Switch.Changed, '#stick_url_to_text')
    def stick_url_to_text_switch(self, message: Message):
        self.state.set_value('stick_url_to_text', message.value)

    @on(Switch.Changed, '#follow_redirects')
    def follow_redirects_switch(self, message: Message):
        self.state.set_value('follow_redirects', message.value)

    @on(Switch.Changed, '#autoping')
    def autoping_switch(self, message: Message):
        self.state.set_value('autoping', message.value)

    @on(AddressInput.Changed, '#address')
    def address_change(self, message: Message):
        self.state.set_value('url', message.value)

        if self.state.get_value('stick_url_to_text'):
            self.state.get_current_text()['url'] = message.value

    @on(Switch.Changed, '#auto_reconnect')
    def auto_reconnect_switch(self, message: Message):
        self.state.set_value('auto_reconnect', message.value)

    @on(Switch.Changed, '#ssl_check')
    def ssl_check_switch(self, message: Message):
        self.state.set_value('ssl_check', message.value)

    @on(Switch.Changed, '#template_url')
    def template_url_switch(self, message: Message):
        self.state.set_value('template_url', message.value)

    @on(Switch.Changed, '#template_headers')
    def template_headers_switch(self, message: Message):
        self.state.set_value('template_headers', message.value)

    @on(Switch.Changed, '#template_data')
    def template_data_switch(self, message: Message):
        self.state.set_value('template_data', message.value)

    @on(Select.Changed, '#method')
    def change_method(self, message: Message):
        self.state.set_value('method', message.value)

        if self.state.get_value('stick_url_to_text'):
            self.state.get_current_text()['method'] = message.value

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
            if selected not in self.state.get_value('texts'):
                text = self.state.get_current_text()
            else:
                text = self.state.get_value('texts')[selected]
                self.state.set_value('text_selected', selected)
            self.state.set_value('text', text['text'])
            if self.state.get_value('stick_url_to_text'):
                self.state.set_value('url', text['url'])
                self.state.set_value('method', text.get('method', 'WS'))
            self.refresh_fields()

    def compose_request_tab(self):
        self.status_label = Label('Disconnected', id='status')
        self.log_field = WsRichLog(highlight=True, markup=True, id='ws_sessions_log')
        self.log_field.styles.border = ('heavy', 'black')

        yield MainGrid(
            ConnectContainer(
                AddressInput(self.state.get_value('url'), placeholder='URL', id='address'),
                SelectSearchable(
                    [(x, x) for x in HTTP_METHODS], id='method', prompt='Method', value='WS', allow_blank=False
                ),
                Button('Connect', id='connect')
            ),
            Horizontal(
                self.status_label,
                LogStatus('', id='log_status'),
            ),
            self.log_field,
            HorizontalHAuto(
                SelectSearchable([('', '')], id='texts', prompt='Text', allow_blank=False),
                NarrowButton('Add', id='add_text'),
                NarrowButton('Delete', id='delete_text'),
                NarrowButton('Edit', id='edit_text'),
                NarrowButton('Copy Curl', id='copy_curl')
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
                NarrowButton('Add', id='add_header'),
                NarrowButton('Delete', id='delete_header'),
                NarrowButton('Edit', id='edit_header'),
            ),
            SwitchContainer(
                Label('\nShow headers (not for WS):'),
                Switch(self.state.get_value('show_headers'), animate=True, id='show_headers')
            ),
            SwitchContainer(
                Label('\nStick url to text:'),
                Switch(self.state.get_value('stick_url_to_text'), animate=True, id='stick_url_to_text')
            ),
            SwitchContainer(
                Label('\nFollow redirects (not for WS):'),
                Switch(self.state.get_value('follow_redirects'), animate=True, id='follow_redirects')
            ),
            SwitchContainer(
                Label('\nAuto ping (WS only):'),
                Switch(self.state.get_value('autoping'), animate=True, id='autoping')
            ),
            SwitchContainer(
                Label('\nAuto reconnect (WS only):'),
                Switch(self.state.get_value('auto_reconnect'), animate=True, id='auto_reconnect')
            ),
            SwitchContainer(
                Label('\nCheck SSL:'),
                Switch(self.state.get_value('ssl_check'), animate=True, id='ssl_check')
            ),
            SwitchContainer(
                Label('\nUse Template for the url:'),
                Switch(self.state.get_value('template_url'), animate=True, id='template_url')
            ),
            SwitchContainer(
                Label('\nUse Template for headers:'),
                Switch(self.state.get_value('template_headers'), animate=True, id='template_headers')
            ),
            SwitchContainer(
                Label('\nUse templates for the data being sent.:'),
                Switch(self.state.get_value('template_data'), animate=True, id='template_data')
            ),
            Label('Configurations'),
            HorizontalHAuto(
                SelectSearchable([('', '')], id='configurations_list', prompt='Configuration', allow_blank=False),
                NarrowButton('Add', id='add_configuration'),
                NarrowButton('Delete', id='delete_configuration'),
                NarrowButton('Edit', id='edit_configuration'),
                NarrowButton('Export', id='export_configuration'),
            ),
            Label('Contexts'),
            HorizontalHAuto(
                SelectSearchable([('', '')], id='contexts_list', prompt='Context', allow_blank=False),
                NarrowButton('Add', id='add_context'),
                NarrowButton('Delete', id='delete_context'),
                NarrowButton('Edit', id='edit_context'),
            ),
            Label('Context Variables (overrides global variables)'),
            HorizontalHAuto(
                OptionList(id='context_variables'),
                NarrowButton('Add', id='add_context_variable'),
                NarrowButton('Delete', id='delete_context_variable'),
                NarrowButton('Edit', id='edit_context_variable'),
            ),
            Label('Global Variables'),
            HorizontalHAuto(
                OptionList(id='global_variables'),
                NarrowButton('Add', id='add_global_variable'),
                NarrowButton('Delete', id='delete_global_variable'),
                NarrowButton('Edit', id='edit_global_variable'),
            ),
        )

    def set_status_text(self, text: str):
        self.status_label.update(text)

    def compose(self) -> ComposeResult:
        with TabbedContent(initial='Request'):
            with TabPane('Request', id='Request'):
                yield from self.compose_request_tab()

            with TabPane('Options', id='Options'):
                yield from self.compse_options_tab()
        yield Footer()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', '-c', dest='config_path', default=None)
    args = parser.parse_args()

    state = State(args.config_path)
    app = WsApp(state)
    app.run()


if __name__ == '__main__':
    main()
