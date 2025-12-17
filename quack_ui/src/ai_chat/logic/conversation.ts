import { ChatMessage } from "./chatMessage"
import { Connection } from "./connection"
import { ConversationManager } from "./conversationManager"


export class ConversationListener {
    public onMessageAdded(_message: ChatMessage): void { }
    public onMessageDeletedFrom(_idx: number, _message: ChatMessage): void { }
    public onModelChanged(_model: string): void { }
    public onWorkspaceChanged(_workspace: string): void { }
    public onSettingChanged(_setting: string, _value: any): void { }
    public onDraftChanged(_draft_text: string, _draft_images: string[]): void { }
}

export class Conversation {
    private listeners: ConversationListener[] = []
    private id: string = ""

    public constructor(
        private model: string = "",
        private messages: ChatMessage[] = [],
        private name: string = "Unnamed Chat",
        private workspace: string = "",
        private draft_text: string = "",
        private draft_images: string[] = []
    ) {}

    public static fromJSON(id: string, json: string): Conversation {
        let data = JSON.parse(json)
        let messages: ChatMessage[] = []
        for (let message of data.messages) {
            messages.push(new ChatMessage(message.text, message.images, message.role))
        }
        let conversation = new Conversation(data.model, messages, data.name, data.workspace, data.draft_text, data.draft_images)
        conversation.setID(id)
        return conversation
    }
    public toJSON() {
        return JSON.stringify({
            model: this.model,
            messages: this.messages,
            name: this.name,
            workspace: this.workspace,
            draft_text: this.draft_text,
            draft_images: this.draft_images
        })
    }

    public setID(id: string) {
        this.id = id
    }
    public getID(): string {
        return this.id
    }

    public getName(): string {
        return this.name
    }
    public setName(name: string): void {
        this.name = name
        for (let listener of this.listeners) {
            listener.onSettingChanged("name", name)
        }
        ConversationManager.saveConversation(this)
    }

    public addListener(listener: ConversationListener): void {
        this.listeners.push(listener)
    }
    public removeListener(listener: ConversationListener): void {
        let idx = this.listeners.indexOf(listener)
        if (idx >= 0) {
            this.listeners.splice(idx, 1)
        }
    }
    public clearListeners(): void {
        this.listeners = []
    }

    public getModel(): string {
        return this.model
    }
    public setModel(model: string): void {
        this.model = model
        for (let listener of this.listeners) {
            listener.onModelChanged(model)
        }
        ConversationManager.saveConversation(this)
    }

    public getWorkspace(): string {
        return this.workspace
    }
    public setWorkspace(workspace: string): void {
        this.workspace = workspace
        for (let listener of this.listeners) {
            listener.onWorkspaceChanged(workspace)
        }
        ConversationManager.saveConversation(this)
    }

    public getMessages(): ChatMessage[] {
        return this.messages
    }

    public addMessage(message: ChatMessage): void {
        this.messages.push(message)
        for (let listener of this.listeners) {
            listener.onMessageAdded(message)
        }
        ConversationManager.saveConversation(this)
    }
    public deleteMessages(message: ChatMessage): void {
        let pos = this.messages.indexOf(message)
        if (pos >= 0) {
            this.messages = this.messages.slice(0, pos)
            for (let listener of this.listeners) {
                listener.onMessageDeletedFrom(pos, message)
            }
            ConversationManager.saveConversation(this)
        }
    }

    public async sendMessage(message: string, images: string[]) {
        // Add the message to the chat history and start streaming the response
        this.addMessage(new ChatMessage(message, images, "user"))
        let messagesCopy = this.getMessages().slice()
        let stream = Connection.getInstance().stream(this.model, this.workspace, messagesCopy)

        // Create message and fill it with the stream
        let chatMessage = new ChatMessage("", [], this.model)
        this.addMessage(chatMessage)
        for await (let token of stream) {
            chatMessage.extendText(token)
        }
        
        // When streaming completed, save the chat history again
        ConversationManager.saveConversation(this)
    }

    public setDraftText(text: string) {
        this.draft_text = text
        for (let listener of this.listeners) {
            listener.onDraftChanged(this.draft_text, this.draft_images)
        }
        ConversationManager.saveConversation(this)
    }
    public getDraftText(): string {
        return this.draft_text
    }
    public setDraftImages(images: string[]) {
        this.draft_images = images
        for (let listener of this.listeners) {
            listener.onDraftChanged(this.draft_text, this.draft_images)
        }
        ConversationManager.saveConversation(this)
    }
    public getDraftImages(): string[] {
        return this.draft_images
    }
}

