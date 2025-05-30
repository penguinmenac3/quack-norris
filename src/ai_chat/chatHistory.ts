import "./chatHistory.css"
import "../webui/md.css"
import { Module } from "../webui/module";
import * as marked from 'marked';
import { ActionButton } from "../webui/components/buttons";
import { iconAIModel, iconCopy, iconEdit, iconRefresh, iconTrash } from "../icons";
import { Chat } from "./chat";
import { copyToClipboard } from "../webui/utils/copy";
import { ConfirmCancelPopup } from "../webui/components/popup";
import { IChatMessage } from "./utils/llms";

export class EditBar extends Module<HTMLDivElement> {
    public constructor(history: ChatHistory, message: ChatMessage, isModel: boolean) {
        super("div", "", "message-tool-bar")
        this.add(new ActionButton(iconCopy, () => {
            copyToClipboard(message.getText().trim())
        }))
        if (isModel) {
            this.add(new ActionButton(iconRefresh, () => {
                let popup = new ConfirmCancelPopup("Are you sure? (This will delete the message and all newer messages!)", "Yes", "Cancel")
                popup.onConfirm = () => {
                    history.rerunMessage(message)
                }
                popup.onCancel = () => { }
            }))
        } else {
            this.add(new ActionButton(iconEdit, () => {
                let popup = new ConfirmCancelPopup("Are you sure? (This will delete the message and all newer messages!)", "Yes", "Cancel")
                popup.onConfirm = () => {
                    let text = message.getText()
                    history.deleteMessagesAfter(message)
                    let chat = history.parent! as Chat
                    chat.chatInput.setInputText(text)
                }
                popup.onCancel = () => { }
            }))
            this.add(new ActionButton(iconTrash, () => {
                let popup = new ConfirmCancelPopup("Are you sure? (This will delete the message and its answer!)", "Yes", "Cancel")
                popup.onConfirm = () => {
                    history.deleteMessage(message)
                }
                popup.onCancel = () => { }
            }))
        }
    }
}

class Thought extends Module<HTMLDivElement> {
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

export class ChatMessage extends Module<HTMLDivElement> implements IChatMessage {
    private content: Module<HTMLDivElement>
    private modelDiv: Module<HTMLDivElement>

    public constructor(history: ChatHistory, private md_content: string, private images: string[], private model: string = "") {
        super("div", "", "message-container")
        this.modelDiv = new Module<HTMLDivElement>("div", model, "model")
        this.add(this.modelDiv)
        if (model == "") {
            this.modelDiv.hide()
            this.setClass("from-user")
        } else {
            this.setClass("from-model")
        }
        if (model != "") {
            this.add(new EditBar(history, this, true))
        } else {
            this.add(new EditBar(history, this, false))
        }
        for (let image of images) {
            let img = new Module<HTMLImageElement>("img")
            img.htmlElement.src = image
            this.add(img)
        }
        this.content = new Module<HTMLDivElement>("div", "", "message-body")
        this.add(this.content)
        this.md_content = ""
        this.appendText(md_content)
    }

    public appendText(text: string) {
        this.md_content += text
        this.content.htmlElement.innerHTML = ""

        let parts = this.md_content.split("</think>")
        for (let idx of parts.keys()) {
            let part = parts[idx].trim()
            if (part.startsWith("<think>")) {
                let html = marked.parse(part.replace("<think>", "")) as string
                let show = idx == parts.length - 1
                this.content.add(new Thought(html, show))
            } else {
                let html = marked.parse(part) as string
                this.content.add(new Module<HTMLDivElement>("div", html))
            }
        }
    }

    public getText(): string {
        return this.md_content
    }

    public getImages(): string[] {
        return this.images
    }

    public setModel(model: string) {
        this.model = model
        this.modelDiv.htmlElement.innerText = model
    }

    public getModel(): string {
        return this.model
    }

    public getRole(): string {
        if (this.model == "") {
            return "user"
        } else {
            return "assistant"
        }
    }
}

export class ChatHistory extends Module<HTMLDivElement> {
    private chatMessages: ChatMessage[] = []

    public constructor(debug: boolean = false) {
        super("div", "", "chat-history")
        if (debug) {
            this.addMessage("How can I help you today?", [], "Quack-Norris")
            this.addMessage("What is 2+2?", [])
            this.addMessage("2 + 2 = 4", [], "Quack-Norris")
            this.addMessage("Are you sure, can you explain me why?", [])
        let md = `You're right to question! It's good to be curious. Let's break down why 2 + 2 = 4.

* **What does "plus" mean?** "Plus" (the + symbol) means we're combining things together.
* **What does "2" represent?** The number 2 represents a quantity – it could be two apples, two fingers, two anything!
* **So, 2 + 2 means:** We're taking two of something *and* another two of the same thing, and then counting how many we have in total.

**Let's use apples as an example:**

Imagine you have 2 apples: 🍎🍎
Then someone gives you 2 more apples: 🍎🍎
Now you have: 🍎🍎🍎🍎

If you count those apples, you have 4 apples.

**Another way to think about it:**

We can use a number line. Start at the number 2. Then, add 2 more, which means moving two spaces to the right. You're now at the number 4.

Therefore, 2 + 2 = 4.



Do you want me to explain it another way, or maybe use a different example?`
            this.addMessage(md, [], "Quack-Norris")
        } else {
            this.loadMessages()
        }
    }

    public addMessage(message: string, images: string[], model: string = "", save: boolean = true) {
        // Add the chat message and give it time to appear
        let chatMessage = new ChatMessage(this, message, images, model)
        this.chatMessages.push(chatMessage)
        this.add(chatMessage)
        setTimeout(() => {
            this.htmlElement.scrollTo(0, this.htmlElement.scrollHeight);
        }, 0)
        // Save changes
        if (save) {
            this.saveMessages()
        }
        return chatMessage
    }

    public getMessages() {
        return this.chatMessages
    }

    public saveMessages() {
        let messages = []
        for (let message of this.chatMessages) {
            messages.push({ "text": message.getText(), "images": message.getImages(), "model": message.getModel() })
        }
        localStorage.setItem("quack-history", JSON.stringify(messages))
    }

    public loadMessages() {
        let messages = JSON.parse(localStorage.getItem("quack-history") || "[]")
        this.htmlElement.innerHTML = ""
        this.chatMessages = []
        for (let message of messages) {
            this.addMessage(message["text"], message["images"], message["model"], false)
        }
    }

    public clear() {
        localStorage.setItem("quack-history", JSON.stringify([]))
        this.loadMessages()
    }

    public deleteMessagesAfter(chatMessage: ChatMessage) {
        let pos = this.chatMessages.indexOf(chatMessage)
        if (pos >= 0) {
            this.chatMessages = this.chatMessages.splice(0, pos)
            this.saveMessages()
            this.loadMessages()
        }
    }

    public deleteMessage(chatMessage: ChatMessage) {
        let pos = this.chatMessages.indexOf(chatMessage)
        if (pos >= 0) {
            this.chatMessages = this.chatMessages.splice(0, pos).concat(this.chatMessages.splice(pos + 2))
            this.saveMessages()
            this.loadMessages()
        }
    }

    public rerunMessage(chatMessage: ChatMessage) {
        let chat = this.parent! as Chat
        let pos = this.chatMessages.indexOf(chatMessage) - 1
        if (pos >= 0) {
            let text = this.chatMessages[pos].getText()
            let images = this.chatMessages[pos].getImages()
            this.chatMessages = this.chatMessages.splice(0, pos)
            this.saveMessages()
            this.loadMessages()
            chat.sendMessage(text, images)
        } else {
            alert("Failed to rerun message, cannot find user request.")
        }
    }
}
