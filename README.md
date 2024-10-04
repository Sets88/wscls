# WSCls

The WebSocket Client Application is a terminal-based graphical user interface (TUI) designed to manage WebSocket connections and configurations. This application provides a user-friendly interface for connecting to WebSocket servers, sending and receiving messages, and managing various configurations and contexts.


![Demo](/data/demo.svg)


## Installation

```bash
pip install wscls
```

## Run

```
wscls
```

## Features

- **WebSocket Connection Management**: Easily connect to and disconnect from WebSocket servers with support for SSL and auto-reconnect options.
- **Message Logging**: View incoming and outgoing WebSocket messages in a rich log with options for word wrapping and auto-scrolling.
- **Configuration Management**: Create, edit, and delete multiple configurations for different WebSocket servers.
- **Context and Variable Management**: Define global and context-specific variables to customize WebSocket requests dynamically.
- **Template Support**: Use templates for URLs and data, allowing for dynamic content generation based on defined variables.
- **User-Friendly Interface**: Intuitive navigation and controls for managing connections, configurations, and messages.

## Main Interface

### Request Tab

- **Address Input**: Enter the WebSocket server URL.
- **Connect Button**: Initiate or terminate the connection to the specified WebSocket server.
- **Status Display**: Shows the current connection status.
- **Log**: Displays incoming and outgoing messages with options to clear and toggle word wrapping.
- **Data selector**: choose predefined data to send.
- **Text Area**: Compose messages to send to the WebSocket server.
- **Send and Ping Buttons**: Send messages or ping the server to check connectivity.

### Options Tab

- **Headers Management**: Add, edit, or delete HTTP headers for WebSocket requests.
- **Auto Ping and Reconnect**: Toggle automatic pinging and reconnection features.
- **SSL Check**: Enable or disable SSL verification for secure connections.
- **Template Usage**: Toggle the use of templates for URLs and data.
- **Configurations**: Manage different server configurations.
- **Contexts and Variables**: Define and manage contexts and their associated variables.

## Templates usage

Templating involves using placeholders within a string that can be replaced with actual values at runtime. This is particularly useful when you need to send requests with dynamic content that changes based on the context or user input.

1. **Template Syntax**:
   - The application uses Python's `string.Template` syntax, where placeholders are defined using the `$` symbol followed by the variable name (e.g., `$variable_name`).
   - For more complex expressions or to avoid ambiguity, you can use curly braces to enclose the variable name (e.g., `${variable_name}`).

2. **Defining Variables**:
   - Variables can be defined globally or within specific contexts. Global variables are available across all contexts, while context-specific variables override global ones within their context.
   - These variables are stored in dictionaries and can be managed through the application's interface.

3. **Using Templates**:
   - **URL Templating**: When the "Use Template for the URL" option is enabled, the application will process the URL field as a template, replacing any placeholders with their corresponding variable values.
   - **Data Templating**: Similarly, when the "Use templates for the data being sent" option is enabled, the message content will be processed as a template before being sent over the WebSocket connection.

4. **Example**:
   - Suppose you have a global variable `username` with the value `Alice`. You can define a URL template like `ws://example.com/user/$username`.
   - When the application processes this template, it will replace `$username` with `Alice`, resulting in the URL `ws://example.com/user/Alice`.


## Hotkeys

- Ctrl + r - Send message(on text area only)
- Ctrl + c - Quit

when focus is on the log area:
- c - Clear log
- w - Toggle word wrap
- s - Toggle auto-scrolling
