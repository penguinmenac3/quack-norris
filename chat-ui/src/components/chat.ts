import "./chat.css"
import { KWARGS, Module } from "../webui/module";
import { ChatInput } from "./chatInput";
import { ChatHistory } from "./chatHistory";

export class Chat extends Module<HTMLDivElement> {
    private chatHistory: ChatHistory
    private chatInput: ChatInput
    
    public constructor(private apiEndpoint: string, private apiKey: string) {
        super("div", "", "chat")
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
            this.chatInput.setModel(kwargs.model)
        }
    }

    public async sendMessage(message: string, model: string) {
        this.chatHistory.addMessage(message)
        let messages = []
        for (let message of this.chatHistory.getMessages()) {
            messages.push({
                "role": message.getRole(),
                "content": message.getText()
            })
        }
        // Create an empty message (that is not saved)
        let chatMessage = this.chatHistory.addMessage("", model, false)

        // Stream in the result into the message entity
        const response = await fetch(this.apiEndpoint + "/chat/completions", {
            method: 'POST',
            headers: {
                Authorization: `Bearer ${this.apiKey}`,
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                model: model,
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
                chatMessage.appendText(text)
            });
            if (dataDone) break;
        }

        // When streaming completed, save the chat history again
        this.chatHistory.saveMessages()
    }

    public newConversation() {
        this.chatHistory.clear()
    }
}
