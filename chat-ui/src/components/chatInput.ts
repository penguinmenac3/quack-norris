import "./chatInput.css"
import { iconCall, iconDropdown, iconMicrophone, iconTrash, iconPlus, iconSend, iconTool, iconRoles, iconAIModel } from "../icons";
import { Module } from "../webui/module";
import { Chat } from "./chat";
import { DropdownButton, ActionButton } from "../webui/components/buttons";
import { ConfirmCancelPopup } from "../webui/components/popup";

export class ChatInput extends Module<HTMLDivElement> {
    private model: string = "quack-norris"
    private input: Module<HTMLTextAreaElement>
    private send: ActionButton
    private call: ActionButton
    private llm: DropdownButton

    public constructor() {
        super("div", "", "chat-input");
        let container = new Module<HTMLDivElement>("div", "", "container")
        this.input = new Module<HTMLTextAreaElement>("textarea")
        this.input.htmlElement.placeholder = "Why is the sky blue?"
        let toolbar = new Module<HTMLDivElement>("div", "", "tool-bar")
        let addMedia = new ActionButton(iconPlus)
        toolbar.add(addMedia)
        let settings = new Module<HTMLSpanElement>("span", "", "settings")
        this.llm = new DropdownButton("")
        this.setModel(this.model)
        settings.add(this.llm)
        let role = new DropdownButton(iconRoles + " General " + iconDropdown)
        settings.add(role)
        let tools = new DropdownButton(iconTool + " Tools " + iconDropdown)
        settings.add(tools)
        toolbar.add(settings)
        let newConversation = new ActionButton(iconTrash)
        toolbar.add(newConversation)
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
            let chat = this.parent! as Chat
            chat.sendMessage(text, this.model)
            this.input.htmlElement.value = ""
            this.onUpdateInput()
        }

        newConversation.onAction = () => {
            let popup = new ConfirmCancelPopup("Are you sure? (Will delete the entire conversation history)", "Yes", "Cancel")
            popup.onConfirm = () => {
                let chat = this.parent! as Chat
                chat.newConversation()
            }
            popup.onCancel = () => { }
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

    public setModel(model: string) {
        this.model = model
        this.llm.htmlElement.innerHTML = iconAIModel + " " + this.model + " " + iconDropdown
    }

    public getModel(): string {
        return this.model
    }

    public setInputText(text: string) {
        this.input.htmlElement.value = text
        this.onUpdateInput()
    }
}