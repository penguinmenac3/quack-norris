# 🦆 Quack Norris - the code savy star 🌟 

![picture of quack norris](quack_norris/ui/assets/icons/duck_low_res.png)

Are you tired of spending hours ⏳ debugging your code? Look no further! Quack Norris 🦆 is here to save the day. This AImazing rubber duck will be your trusty AI companion 🤖, helping you tackle anything on your PC 💻.

**Unified API Access to Agentic AI**: Experience seamless integration with leading language models through our unified API. This innovative platform supports agentic AI, allowing tools and retrieval-augmented generation (RAG) functionalities to be transparently utilized by any connecting app - whether it's focused on chat or other tasks. 🤖💬

**Global Conversations**: Our advanced feature intelligently aggregates conversations from various connections into a cohesive global conversation, powered by the `quack-norris-global` model (itself using any model you want in the background). This ensures continuity and context across multiple interactions, enhancing your user experience and productivity. 🚀🌐


## 🛠️ Installation

```bash
# for server use (just backend)
pip install quack-norris

# for desktop use (includes ui)
pip install quack-norris[ui]
```


## 👨‍💻 Usage 

Run the ui or server from the commandline.
```bash
# run server
quack-norris-server

# run ui (including local server, if not present)
quack-norris-ui
```

If you want to add quack norris to the autostart or the startmenu on windows, simply find the `quack-norris-ui.exe`, wherever your python installation put it and add a **link** to it to your startmenu (in the right click settings, you can even configure an icon). You can find the startmenu here: `C:\Users\YOUR_USERNAME\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup`.

### 🎨 Config

Config files can be created in the current working directory or in your users config folder `~/.config/quack_norris/`.

In your `server.json` and in your `ui.json` you can configure the server host and port.
```json
{
  "host": "127.0.0.1",
  "port": 11337
}
```

Additionally, in your `ui.json` you can configure the launcher look and feel.
```json
{
  ...
  "launcher_ctrl_click_to_exit": false,
  "launcher_size": [84, 84],
  "launcher_icon": "my_icon.png"
}
```


### 🌐 API

The server exposes an OpenAI style API for you to use in other tools as well.
However, to access all features, you need to know the following:
* `model = "quack-norris"` uses whatever is selected by quack norris (user, agent or router)
  - `model = "quack-norris:code"` hints that we prefer a code savy model
* `model = "quack-norris-global"` (and variants) use the same conversation accross all connections (not per connection)
  - allows you to have a conversation across multiple applications (breaking boundaries between your IDE and quack-norris-ui)
  - `quack-norris-ui` uses the global model by default
* `/cmd` - slash-commands allow you to interact with the server instead of the model (returns the response of the command instead of a model response)
  - `/fetch` gets the messages in the chat since your last message
  - `/new [name]` starts a new chat with the model using the (optional) name (use timestamp as name for unnamed chats)
  - `/clear` is an alias for `/new`
  - `/rename name` rename the current conversation to a new name
  - `/select name` change to another conversation
  - `/model modelname` change the model of the conversation (e.g. `/model llama3.2:7b`)
  - `/list` list all available conversations


## 💡 Roadmap

* Server
  - [X] Provide OpenAI Rest API Endpoint
  - [ ] Route requests to LLM via an OpenAI API (proxy)
  - [ ] Route quack norris model variants to custom chat handler
  - [ ] Implement commands for quack norris chat handler
  - [ ] Implement named and unnamed chats (history management)
  - [ ] Implement global chat mangling
  - [ ] Implement quack norris chat router (agentic, tools)
  - [ ] Implement agentic AI core
  - [ ] Implement tool calling (for AI and User)
  - Implement tools
    * [ ] Web Search (get urls + abstract)
    * [ ] Web Scraper (get content of url as text)
    * [ ] Search Wikipedia (get article names + abstract)
    * [ ] Read Wikipedia (get wikipedia article on topic as text)
    * [ ] RaG Context Retriever (get filename and text snippet as context)
    * [ ] Document Read (printout content of a file)
    * [ ] Document Writer (write text to a file)
    * [ ] Paper Search (Arxiv, Google Scholar)
    * [ ] Paper Summarize - Pass 1 (fast, short summary of a transcribed pdf)
    * [ ] Paper Summarize - Pass 2 (detailed summary of a pass 1 summarized paper)
    * [ ] PDF Downloader (Arxiv, Google Scholar or url)
    * [ ] PDF Transcribe (pdf to markdown/text)
    * [ ] Podcast Creator (generate a podcast explaining the content of a document)
  - [ ] Provide E-Mail endpoint (write mail and AI will respond to you)
  - [ ] Provide Phone Call endpoint (call via phone and AI will respond to you)
  - [ ] Startup/boot a model server, if needed (e.g. raspi starts gaming PC)
* [ ] UI
  - [ ] A floating duck (movable)
  - [ ] Double click opens a chat window with buttons for actions
  - Implement Actions:
    * [ ] Take Screenshot (into chat input)
    * [ ] Transcribe Audio (into chat input)
      - use transcript to chat with AI
      - use "Document Writer" tool to take notes
    * [ ] Call (transcript is sent after a pause, response is read and it listenes again for user input)
    * [ ] Manage Chats
      - New Chat
      - Switch/Change Chat
      - Archive Chat
      - Change Chat's Model


## 👥 Contributing

Feel free to make this code better by forking, improving the code and then pull requesting.

I try to keep the dependency list of the repository as small as possible.
Hence, please try to not include unnescessary dependencies, just because they save you two lines of code.

When in doubt, if I will like your contribution, check the [.continuerules](.continuerules) for AI assistants.
The rules for AI will also apply to human contributors.


## ⚖️ License

Quack Norris is licensed under the permissive MIT license -- see [LICENSE](LICENSE) for details.
