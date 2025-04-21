import "./chatInput.css"
import { iconCall, iconMicrophone, iconPlus, iconSend, iconTool, iconWeb, iconBook } from "../icons";
import { Module } from "../webui/module";
import { Chat } from "./chat";
import { ActionButton } from "../webui/components/buttons";

export class ChatInput extends Module<HTMLDivElement> {
    private input: Module<HTMLTextAreaElement>
    private send: ActionButton
    private call: ActionButton

    public constructor() {
        super("div", "", "chat-input");
        let container = new Module<HTMLDivElement>("div", "", "container")
        this.input = new Module<HTMLTextAreaElement>("textarea")
        this.input.htmlElement.placeholder = "Why is the sky blue?"
        let toolbar = new Module<HTMLDivElement>("div", "", "tool-bar")
        let addMedia = new ActionButton(iconPlus)
        toolbar.add(addMedia)
        let tools = new Module<HTMLSpanElement>("span", "", "fill-width")
        let web_search = new ActionButton(iconWeb + " Web")
        web_search.setClass("with-text")
        tools.add(web_search)
        // let code = new ActionButton(iconTerminal + " Code")
        // code.setClass("with-text")
        // tools.add(code)
        let rag = new ActionButton(iconBook + " RaG")
        rag.setClass("with-text")
        tools.add(rag)
        let extra_tools = new ActionButton(iconTool + " Tools")
        extra_tools.setClass("with-text")
        tools.add(extra_tools)
        toolbar.add(tools)
        let microphone = new ActionButton(iconMicrophone)
        toolbar.add(microphone)
        this.call = new ActionButton(iconCall)
        toolbar.add(this.call)
        this.send = new ActionButton(iconSend)
        this.send.hide()
        toolbar.add(this.send)
        container.add(this.input)
        container.add(toolbar)
        this.add(container)

        // Add logic here that connects ui elements        
        this.input.htmlElement.onkeyup = (ev: KeyboardEvent) => {
            if (this.input.htmlElement.value != "") {
                // Catch CTRL + Enter to send message
                if (ev.ctrlKey && ev.key == "Enter") {
                    this.send.onAction()
                }
            }
            this.onUpdateInput()
        }

        this.send.onAction = () => {
            let text = this.input.htmlElement.value
            let images: string[] = []
            let chat = this.parent! as Chat
            chat.sendMessage(text, images)
            this.input.htmlElement.value = ""
            this.onUpdateInput()
        }
    }

    private onUpdateInput() {
        // Update the avaialble tools based on the input
        if (this.input.htmlElement.value != "") {
            this.call.hide()
            this.send.show()
        } else {
            this.send.hide()
            this.call.show()
        }
        // Resize the input element to match content size
        this.input.htmlElement.style.height = "auto"
        let height = this.input.htmlElement.scrollHeight
        if (height >= window.innerHeight * 0.4) {
            height = window.innerHeight * 0.4
        }
        this.input.htmlElement.style.height = "" + height + "px"
    }

    public setInputText(text: string) {
        this.input.htmlElement.value = text
        this.onUpdateInput()
    }
}