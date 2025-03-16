import "./chat.css"
import { Module } from "../webui/module";
import { ChatInput } from "./chatInput";
import { ChatHistory } from "./chatHistory";

export class Chat extends Module<HTMLDivElement> {
    private chatHistory: ChatHistory
    private chatInput: ChatInput
    
    public constructor() {
        super("div", "", "chat")
        this.chatHistory = new ChatHistory()
        this.add(this.chatHistory)
        this.chatInput = new ChatInput()
        this.add(this.chatInput)
    }

    public sendMessage(message: string) {
        this.chatHistory.addMessage(message)
        this.chatHistory.addMessage("TODO send message to server and update the message using streaming", "UI")
    }
}
