import "./chat.css"
import { KWARGS, Module } from "../webui/module";
import { ChatInput } from "./chatInput";
import { ChatHistory } from "./chatHistory";
import { ActionButton, DropdownButton } from "../webui/components/buttons";
import { iconAIModel, iconDropdown, iconSettings, iconTrash } from "../icons";
import { iconBars } from "../webui/icons";
import { ConfirmCancelPopup, ExitablePopup } from "../webui/components/popup";
import { APIType, LLMs } from "./utils/llms";
import { FormHeading, FormInput, FormLabel, FormRadioButtonGroup, FormSubmit, FormVSpace } from "../webui/components/form";
import { Tools } from "./utils/tools";

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
            let popup = new ExitablePopup("popupContent-fullscreen")
            // LLMs
            popup.add(new FormHeading("LLM Connections"))
            let connections = LLMs.getInstance().getConnections()
            for (let connection of connections) {
                popup.add(new RemovableItem(
                    connection.name + " (" + connection.apiEndpoint + ")",
                    () => { LLMs.getInstance().removeConnection(connection) }
                ))
            }
            popup.add(new FormHeading("Add LLM Server", "h2"))
            popup.add(new FormLabel("name"))
            let apiName = new FormInput("apiName", "Ollama", "text")
            popup.add(apiName)
            popup.add(new FormLabel("apiEndpoint"))
            let apiEndpoint = new FormInput("apiEndpoint", "https://localhost:11434/v1", "text")
            popup.add(apiEndpoint)
            popup.add(new FormLabel("apiKey"))
            let apiKey = new FormInput("apiKey", "f5a20...", "password")
            popup.add(apiKey)
            popup.add(new FormLabel("model"))
            let model = new FormInput("model", "(leave blank for autodetect)", "text")
            popup.add(model)
            popup.add(new FormLabel("apiType"))
            let apiTypeOptions = [APIType.OpenAI, APIType.AzureOpenAI]
            let apiType = new FormRadioButtonGroup("apiType", apiTypeOptions)
            apiType.value(0)
            popup.add(apiType)
            let addLLM = new FormSubmit("Add LLM Server", "buttonWide")
            addLLM.onClick = () => {
                let selectedApi = apiType.value() as any
                if (!(selectedApi instanceof String)) {
                    selectedApi = apiTypeOptions[selectedApi]
                }
                if (apiName.value() == "") {
                    alert("name must not be empty!")
                    return
                }
                if (apiEndpoint.value() == "") {
                    alert("apiEndpoint must not be empty!")
                    return
                }
                if (apiKey.value() == "") {
                    alert("apiKey must not be empty!")
                    return
                }
                LLMs.getInstance().addConnection(
                    apiName.value(),
                    apiEndpoint.value(),
                    apiKey.value(),
                    model.value(),
                    selectedApi,
                )
                popup.dispose()
            }
            popup.add(addLLM)
            // Tools
            popup.add(new FormVSpace("3em"))
            popup.add(new FormHeading("Tool Connections"))
            let tools = Tools.getInstance().getConnections()
            for (let connection of tools) {
                popup.add(new RemovableItem(
                    connection.apiEndpoint,
                    () => { Tools.getInstance().removeConnection(connection) }
                ))
            }
            popup.add(new FormHeading("Add Tool Server", "h2"))
            popup.add(new FormLabel("toolEndpoint"))
            let toolEndpoint = new FormInput("toolEndpoint", "https://localhost:1337", "text")
            popup.add(toolEndpoint)
            popup.add(new FormLabel("toolKey"))
            let toolKey = new FormInput("toolKey", "f5a20...", "password")
            popup.add(toolKey)
            let addTool = new FormSubmit("Add Tool Server", "buttonWide")
            addTool.onClick = () => {
                Tools.getInstance().addConnection(toolEndpoint.value(), toolKey.value())
                popup.dispose()
            }
            popup.add(addTool)
        }
    }

    public update(_kwargs: KWARGS, _changedPage: boolean): void { }

    public async sendMessage(message: string, images: string[]) {
        this.chatHistory.addMessage(message, images)
        // Create an empty message (that is not saved)
        let chatMessage = this.chatHistory.addMessage("", [], this.model, false)

        let stream = LLMs.getInstance().chat(this.model, this.chatHistory.getMessages())
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


class RemovableItem extends Module<HTMLDivElement> {
    constructor(text: string, callback: CallableFunction) {
        super("div", text, "removableItem")
        let button = new ActionButton(iconTrash)
        button.setClass("right")
        button.onAction = () => { this.hide(); callback() }
        this.add(button)
    }
}