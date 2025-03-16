import "./chatInput.css"
import { iconCall, iconDropdown, iconMicrophone, iconPlus, iconSend, iconTool } from "../icons";
import { Module } from "../webui/module";
import { Chat } from "./chat";

export class ActionButton extends Module<HTMLSpanElement> {
    public constructor(icon: string) {
        super("span", icon, "action");
        this.htmlElement.onclick = () => this.onAction()
    }

    public onAction() { alert("Not implemented yet!") }
}

export class DropdownButton extends Module<HTMLSpanElement> {
    public constructor(icon: string) {
        super("span", icon, "dropdown");
        this.htmlElement.onclick = () => this.onAction()
    }
    public onAction() { alert("Not implemented yet!") }
}


export class ChatInput extends Module<HTMLDivElement> {
    public constructor() {
        super("div", "", "chat-input");
        let container = new Module<HTMLDivElement>("div", "", "container")
        let input = new Module<HTMLTextAreaElement>("textarea")
        input.htmlElement.placeholder = "Why is the sky blue?"
        let toolbar = new Module<HTMLDivElement>("div", "", "tool-bar")
        let addMedia = new ActionButton(iconPlus)
        toolbar.add(addMedia)
        let settings = new Module<HTMLSpanElement>("span", "", "settings")
        let llm = new DropdownButton("Quack Norris " + iconDropdown)
        settings.add(llm)
        let tools = new DropdownButton(iconTool + " Tools " + iconDropdown)
        settings.add(tools)
        toolbar.add(settings)
        let microphone = new ActionButton(iconMicrophone)
        toolbar.add(microphone)
        let call = new ActionButton(iconCall)
        toolbar.add(call)
        let send = new ActionButton(iconSend)
        send.hide()
        toolbar.add(send)
        container.add(input)
        container.add(toolbar)
        this.add(container)

        // Add logic here that connects ui elements
        function onUpdateInput() {
            // Update the avaialble tools based on the input
            if (input.htmlElement.value != "") {
                call.hide()
                send.show()
            } else {
                send.hide()
                call.show()
            }
            // Resize the input element to match content size
            input.htmlElement.style.height = "auto"
            let height = input.htmlElement.scrollHeight
            if (height >= window.innerHeight * 0.4) {
                height = window.innerHeight * 0.4
            }
            input.htmlElement.style.height = "" + height + "px"
        }

        input.htmlElement.onkeyup = (ev: KeyboardEvent) => {
            if (input.htmlElement.value != "") {
                // Catch CTRL + Enter to send message
                if (ev.ctrlKey && ev.key == "Enter") {
                    send.onAction()
                }
            }
            onUpdateInput()
        }

        send.onAction = () => {
            let text = input.htmlElement.value
            let chat = this.parent! as Chat
            chat.sendMessage(text)
            input.htmlElement.value = ""
            onUpdateInput()
        }
    }
}