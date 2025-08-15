import "./chat.css"
import { KWARGS, Module } from "../webui/module";
import { ChatInput } from "./chatInput";
import { ChatHistory } from "./chatHistory";
import { ActionButton, DropdownButton } from "../webui/components/buttons";
import { iconAIModel, iconDropdown, iconSettings, iconTrash } from "../icons";
import { iconBars } from "../webui/icons";
import { ConfirmCancelPopup } from "../webui/components/popup";
import { LLMs } from "./utils/llms";
import { settings_popup } from "./settings_popup";

export class Chat extends Module<HTMLDivElement> {
    public chatHistory: ChatHistory
    public chatInput: ChatInput
    private llm: DropdownButton
    private model: string = "loading..."
    
    public constructor() {
        super("div", "", "chat")
        let header = new Module<HTMLDivElement>("div", "", "chat-header")
        let conversations = new ActionButton(iconBars)
        header.add(conversations)
        let newConversation = new ActionButton(iconTrash)
        header.add(newConversation)
        let quick_settings = new Module<HTMLSpanElement>("span", "", "fill-width")
        this.llm = new DropdownButton(iconAIModel + " " + this.model + " " + iconDropdown, null, true)
        this.llm.onAction = async () => {
            let models = await LLMs.getInstance().getModels()
            let actions = new Map<string, CallableFunction>()
            for (let model of models) {
                actions.set(model, () => {
                    this.model = model
                    localStorage["quack-norris-model"] = this.model
                    this.llm.htmlElement.innerHTML = iconAIModel + " " + this.model + " " + iconDropdown
                    return true
                })
            }
            this.llm.showMenu(actions)
        }
        window.setTimeout(async () => {
            let models = await LLMs.getInstance().getModels()
            if (localStorage["quack-norris-model"]) {
                this.model = localStorage["quack-norris-model"]
            }
            // If the model does not exist, just take the first
            if (!models.includes(this.model)) {
                if (models[0]) {
                    this.model = models[0]
                    localStorage["quack-norris-model"] = this.model
                } else {
                    this.model = "(no model found)"
                }
            }
            this.llm.htmlElement.innerHTML = iconAIModel + " " + this.model + " " + iconDropdown
        }, 100)
        quick_settings.add(this.llm)
        //let role = new DropdownButton(iconRoles + " General " + iconDropdown)
        // let roles = new Map<string, CallableFunction>()
        // roles.set("General", () => true)  // FIXME add roles like with LLM, but for now do nothing
        // role.setOptions(roles)
        // header.add(role)
        header.add(quick_settings)
        let settings = new ActionButton(iconSettings)
        header.add(settings)
        this.add(header)
        this.chatHistory = new ChatHistory()
        this.add(this.chatHistory)
        this.chatInput = new ChatInput()
        this.add(this.chatInput)


        newConversation.onAction = () => {
            let popup = new ConfirmCancelPopup("Are you sure? (Will delete the entire conversation history)", "Yes", "Cancel")
            popup.onConfirm = () => {
                this.newConversation()
            }
            popup.onCancel = () => { }
        }

        settings.onAction = () => {
            settings_popup();
        }
    }

    public update(_kwargs: KWARGS, _changedPage: boolean): void { }

    public async sendMessage(message: string, images: string[]) {
        // Add the message to the chat history and start streaming the response
        this.chatHistory.addMessage(message, images)
        let stream = LLMs.getInstance().chat(this.model, this.chatHistory.getMessages())

        // Create message and fill it with the stream
        let chatMessage = this.chatHistory.addMessage("", [], this.model, false)
        for await (let token of stream) {
            chatMessage.appendText(token)
        }

        // When streaming completed, save the chat history again
        this.chatHistory.saveMessages()
    }

    public newConversation() {
        this.chatHistory.clear()
    }
}
