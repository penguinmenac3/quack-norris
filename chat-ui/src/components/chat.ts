import "./chat.css"
import { Module } from "../webui/module";
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

    public async sendMessage(message: string, model: string) {
        this.chatHistory.addMessage(message)
        let messages = []
        for (let message of this.chatHistory.getMessages()) {
            messages.push({
                "role": message.getRole(),
                "content": message.getText()
            })
        }
        let chatMessage = this.chatHistory.addMessage("", model)
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
    }
}
