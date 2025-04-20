import "./chat.css"
import { KWARGS, Module } from "../webui/module";
import { ChatInput } from "./chatInput";
import { ChatHistory } from "./chatHistory";
import { ActionButton, DropdownButton } from "../webui/components/buttons";
import { iconAIModel, iconDropdown } from "../icons";
import { iconBars } from "../webui/icons";

export class Chat extends Module<HTMLDivElement> {
    public chatHistory: ChatHistory
    public chatInput: ChatInput
    private llm: DropdownButton
    private model: string = "quack-norris"
    
    public constructor(private apiEndpoint: string, private apiKey: string) {
        super("div", "", "chat")
        let header = new Module<HTMLDivElement>("div", "", "chat-header")
        let conversations = new ActionButton(iconBars)
        header.add(conversations)
        this.llm = new DropdownButton(iconAIModel + " " + this.model + " " + iconDropdown)
        this.llm.onAction = async () => {
            let models = await this.getModels()
            let actions = new Map<string, CallableFunction>()
            for (let model of models) {
                actions.set(model, () => {
                    this.model = model
                    this.llm.htmlElement.innerHTML = iconAIModel + " " + this.model + " " + iconDropdown
                    return true
                })
            }
            this.llm.showMenu(actions)
        }
        header.add(this.llm)
        this.add(header)
        this.chatHistory = new ChatHistory()
        this.add(this.chatHistory)
        this.chatInput = new ChatInput()
        this.add(this.chatInput)
    }

    public update(kwargs: KWARGS, _changedPage: boolean): void {
        if (kwargs.apiEndpoint) {
            this.apiEndpoint = kwargs.apiEndpoint
        }
        if (kwargs.apiKey) {
            this.apiKey = kwargs.apiKey
        }
        if (kwargs.model) {
            this.model = kwargs.model
        }
        window.location.hash = "chat"
    }

    public async sendMessage(message: string, images: string[]) {
        this.chatHistory.addMessage(message, images)
        let messages = []
        for (let message of this.chatHistory.getMessages()) {
            let content: any[] = [{
                "type": "text",
                "text": message.getText()
            }]
            for (let image of message.getImages()) {
                content.push({
                    "type": "image_url",
                    "image_url": { "url": image }
                })
            }
            messages.push({
                "role": message.getRole(),
                "content": content
            })
        }
        // Create an empty message (that is not saved)
        let chatMessage = this.chatHistory.addMessage("", [], this.model, false)

        // Stream in the result into the message entity
        const response = await fetch(this.apiEndpoint + "/chat/completions", {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${this.apiKey}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                model: this.model,
                messages: messages,
                stream: true,
            }),
        });
        const reader = response.body?.pipeThrough(new TextDecoderStream()).getReader();
        if (!reader) return;
        // eslint-disable-next-line no-constant-condition
        while (true) {
            // eslint-disable-next-line no-await-in-loop
            const { value, done } = await reader.read();
            if (done) break;
            let dataDone = false;
            const arr = value.split('\n');
            arr.forEach((data) => {
                if (data.length === 0) return; // ignore empty message
                if (data.startsWith(':')) return; // ignore sse comment message
                if (data === 'data: [DONE]') {
                    dataDone = true;
                    return;
                }
                const json = JSON.parse(data.substring(6));
                let text = json.choices[0]["delta"]["content"]
                chatMessage.setModel(json.model)
                chatMessage.appendText(text)
            });
            if (dataDone) break;
        }

        // When streaming completed, save the chat history again
        this.chatHistory.saveMessages()
    }

    public async getModels(): Promise<string[]> {
        const response = await fetch(this.apiEndpoint + "/models", {
            method: 'GET',
            headers: {
                Authorization: `Bearer ${this.apiKey}`,
                'Content-Type': 'application/json',
            },
        })
        let data = await response.json()
        let models = []
        for (let model of data["data"]) {
            models.push(model["id"])
        }
        return models
    }

    public newConversation() {
        this.chatHistory.clear()
    }
}
