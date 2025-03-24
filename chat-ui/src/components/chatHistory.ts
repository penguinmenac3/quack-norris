import "./chatHistory.css"
import { Module } from "../webui/module";
import * as marked from 'marked';

export class EditBar extends Module<HTMLDivElement> {
    public constructor(isModel: boolean) {
        super("div", "", "edit-bar")
        if (isModel) {
            this.htmlElement.innerHTML = "TODO (Model Edit)"
        } else {
            this.htmlElement.innerHTML = "TODO (User Edit)"
        }
    }
}

export class ChatMessage extends Module<HTMLDivElement> {
    private content: Module<HTMLDivElement>

    public constructor(private md_content: string, private model: string = "") {
        super("div", "", "message-container")
        if (model != "") {
            this.setClass("from-model")
            this.add(new Module<HTMLDivElement>("div", model, "model"))
        } else {
            this.setClass("from-user")
        }
        let html = marked.parse(md_content) as string
        this.content = new Module<HTMLDivElement>("div", html, "message-body")
        this.add(this.content)
        if (model != "") {
            this.add(new EditBar(true))
        } else {
            this.add(new EditBar(false))
        }
    }

    public appendText(text: string) {
        this.md_content += text
        let html = marked.parse(this.md_content) as string
        this.content.htmlElement.innerHTML = html
    }

    public getText(): string {
        return this.md_content
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
            this.addMessage("How can I help you today?", "Quack-Norris")
            this.addMessage("What is 2+2?")
            this.addMessage("2 + 2 = 4", "Quack-Norris")
            this.addMessage("Are you sure, can you explain me why?")
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
            this.addMessage(md, "Quack-Norris")
        }
    }

    public addMessage(message: string, model: string = "") {
        let chatMessage = new ChatMessage(message, model)
        this.chatMessages.push(chatMessage)
        this.add(chatMessage)
        setTimeout(() => {
            this.htmlElement.scrollTo(0, this.htmlElement.scrollHeight);
        }, 0);
        return chatMessage;
    }

    public getMessages() {
        return this.chatMessages
    }
}
