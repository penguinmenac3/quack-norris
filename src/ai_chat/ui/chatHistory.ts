import "./chatHistory.css"
import "../../webui/md.css"
import * as marked from 'marked';
import { Module } from "../../webui/module";
import { ActionButton } from "../../webui/components/buttons";
import { copyToClipboard } from "../../webui/utils/copy";
import { ConfirmCancelPopup } from "../../webui/components/popup";
import { iconAIModel, iconCopy, iconEdit, iconRefresh, iconTrash } from "../../icons";
import { Conversation, ConversationListener } from "../logic/conversation";
import { ChatMessage, ChatMessageListener } from "../logic/chatMessage";
import { ConversationManager, ConversationManagerListener } from "../logic/conversationManager";

export class EditBarComponent extends Module<HTMLDivElement> {
    public constructor(message: ChatMessage) {
        super("div", "", "message-tool-bar")
        this.add(new ActionButton(iconCopy, () => {
            copyToClipboard(message.getText().trim())
        }))
        if (message.getRole() != "user") {
            this.add(new ActionButton(iconRefresh, () => {
                let popup = new ConfirmCancelPopup("Are you sure? (This will delete the message and all newer messages!)", "Yes", "Cancel")
                popup.onConfirm = () => {
                    let conversation = ConversationManager.getCurrentConversation()
                    if (conversation) {
                        let messages = conversation.getMessages()
                        let idx = messages.indexOf(message) - 1
                        if (idx >= 0) {
                            let userMessage = messages[idx]
                            conversation.deleteMessages(userMessage)
                            conversation.sendMessage(userMessage.getText(), userMessage.getImages())
                        }
                    }
                }
                popup.onCancel = () => { }
            }))
        } else {
            this.add(new ActionButton(iconEdit, () => {
                let popup = new ConfirmCancelPopup("Are you sure? (This will delete the message and all newer messages!)", "Yes", "Cancel")
                popup.onConfirm = () => {
                    let conversation = ConversationManager.getCurrentConversation()
                    if (conversation) {
                        conversation.setDraftText(message.getText())
                        conversation.setDraftImages(message.getImages())
                        conversation.deleteMessages(message)
                    }
                }
                popup.onCancel = () => { }
            }))
            this.add(new ActionButton(iconTrash, () => {
                let popup = new ConfirmCancelPopup("Are you sure? (This will delete the message and all newer messages!)", "Yes", "Cancel")
                popup.onConfirm = () => {
                    let conversation = ConversationManager.getCurrentConversation()
                    if (conversation) {
                        conversation.deleteMessages(message)
                    }
                }
                popup.onCancel = () => { }
            }))
        }
    }
}

class ThoughtComponent extends Module<HTMLDivElement> {
    public constructor(text: string, show: boolean) {
        super("div", "", "thought")
        var header = new Module<HTMLDivElement>("div", iconAIModel + " Thought (click to expand/collapse)", "thought-header")
        this.add(header)
        var content = new Module<HTMLDivElement>("div", text)
        if (!show) {
            content.hide()
        }
        this.add(content)

        this.htmlElement.onclick = () => {
            if (content.isVisible()) {
                content.hide()
            } else {
                content.show()
            }
        }
    }
}

export class ChatMessageComponent extends Module<HTMLDivElement> {
    private content: Module<HTMLDivElement>
    private modelDiv: Module<HTMLDivElement>

    public constructor(message: ChatMessage) {
        super("div", "", "message-container")
        this.modelDiv = new Module<HTMLDivElement>("div", message.getRole(), "model")
        this.add(this.modelDiv)
        if (message.getRole() == "user") {
            this.modelDiv.hide()
            this.setClass("from-user")
        } else {
            this.setClass("from-model")
        }
        this.add(new EditBarComponent(message))
        for (let image of message.getImages()) {
            let img = new Module<HTMLImageElement>("img")
            img.htmlElement.src = image
            this.add(img)
        }
        this.content = new Module<HTMLDivElement>("div", "", "message-body")
        this.add(this.content)
        this.renderText(message)

        let listener = new ChatMessageListener()
        listener.onExtendText = (_chunk: string) => {
            this.renderText(message)
        }
        message.addListener(listener)
    }

    private renderText(message: ChatMessage) {
        this.content.htmlElement.innerHTML = ""

        let parts = message.getText().split("</think>")
        for (let idx of parts.keys()) {
            let part = parts[idx].trim()
            if (part.startsWith("<think>")) {
                let html = marked.parse(part.replace("<think>", "")) as string
                let show = idx == parts.length - 1
                this.content.add(new ThoughtComponent(html, show))
            } else {
                let html = marked.parse(part) as string
                this.content.add(new Module<HTMLDivElement>("div", html))
            }
        }
    }
}

export class ChatHistory extends Module<HTMLDivElement> {
    public constructor() {
        super("div", "", "chat-history")
        let listener = new ConversationManagerListener()
        listener.onConversationSelected = (_id: string, conversation: Conversation) => {
            this.renderMessages(conversation)
        }
        ConversationManager.addListener(listener)

        let conversation = ConversationManager.getCurrentConversation()
        if (conversation) {
            this.renderMessages(conversation)
        }
    }

    public addMessage(message: ChatMessage) {
        // Add the chat message and give it time to appear
        let chatMessageComponent = new ChatMessageComponent(message)
        this.add(chatMessageComponent)
        setTimeout(() => {
            this.htmlElement.scrollTo(0, this.htmlElement.scrollHeight);
        }, 0)
    }

    public renderMessages(conversation: Conversation) {
        this.htmlElement.innerHTML = ""
        for (let message of conversation.getMessages()) {
            this.addMessage(message)
        }
        let listener = new ConversationListener()
        listener.onMessageAdded = (message: ChatMessage) => {
            this.addMessage(message)
        }
        listener.onMessageDeletedFrom = (idx: number, _message: ChatMessage) => {
            while (this.htmlElement.children.length > idx) {
                this.htmlElement.removeChild(this.htmlElement.children[idx]);
            }
        }
        conversation.addListener(listener)
    }
}
