# 🦆 Quack Norris - the code savy star 🌟 

![picture of quack norris](images/duck_low_res.png)

Are you tired of spending hours ⏳ debugging your code? Look no further! Quack Norris 🦆 is here to save the day. This AImazing rubber duck will be your trusty AI companion 🤖, helping you tackle anything on your PC 💻.

**Agentic AI Core**: Experience agentic AI using any language model provider through this UI. This innovative platform allows tools and retrieval-augmented generation (RAG) functionalities to be used with ease. 🤖💬

![agentic-core-visualization](./docs/agent.excalidraw.svg)

## 👨‍💻 Usage 

Visit https://penguinmenac3.github.io/quack-norris/ and install it as a web app.
Additionally you can use the [quack-norris-floaty](https://penguinmenac3.github.io/quack-norris-floaty/) to have the app available on your desktop at all times, but there some features might not work fully.

### Enable CORS for OLLAMA

When using ollama you have to enable CORS so that the app cann access it from the webui.
To achieve this, add `OLLAMA_ORIGINS=*` to the environment variables.

![Environment variables on windows](images/OllamaCORSConfig.png)

### 🎨 Config

When you open the app for the first time, it will try to use your local ollama as an LLM provider.
If you do not have ollama or want to use any Open AI compatible LLM service, you can open the settings and configure your LLM connections there. (Note that the server has to allow cross-origin requests.)

Additionally, you can add MCP tools hosted via http. Note stdio MCPs do not work, since we are a web application.


## 💡 Roadmap

- UX / UI
  * [ ] Settings
    - [X] Configure connections to LLMs
    - [%] Configure connections to tools
      * [ ] Provide http url to MCP server + headers for login
      * [ ] Allow declaring that a tool is in Web or RaG group
  * [ ] Manage Chats / Conversations
    - [X] New chat
    - [ ] Change icon for new chat
    - [X] Change model for current chat
    - [ ] Download current chat as markdown
    - [ ] Reopen old conversation
    - [ ] Delete old conversation
  * [X] Image support (allow pasting, dragging or uploading an image / screenshot)
  * [ ] Activate / deactivate tools
    - [ ] Quick MCP tools (Web, RaG, Deep Thought = agentic loop)
      * [ ] Button for Agentic
    - [ ] Other MCP tools (via dropdown)
- AI Features
  * [ ] Agentic core loop (collect context by calling tools, aggregate answer)
- Audio Features (far future)
  * [ ] Transcribe Audio (Speech-To-Text into chat input)
  * [ ] Read out responses (Text-To-Speech)
  * [ ] Call (transcript is sent after a pause, response is read and it listenes again for user input)

## 👥 Contributing

Feel free to make this code better by forking, improving the code and then pull requesting.

I try to keep the dependency list of the repository as small as possible.
Hence, please try to not include unnescessary dependencies, just because they save you two lines of code.

When in doubt, if I will like your contribution, check the [.continuerules](.continuerules) for AI assistants.
The rules for AI will also apply to human contributors.

### Building the Chat-UI

Run the build command, add and commit the dist folder and then push this folger to gh-pages.

```
npm run build
rm dist/favicon.kra
git add -f dist
git commit -m "Build gh-pages."
git push
git subtree push --prefix dist origin gh-pages
```

### Software Architecture

The software architecture is documented in this excalidraw.

![software-architecture](./docs/architecture.excalidraw.svg)

## ⚖️ License

Quack Norris is licensed under the permissive MIT license -- see [LICENSE](LICENSE) for details.
