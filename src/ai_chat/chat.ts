import "./chat.css"
import { KWARGS, Module } from "../webui/module";
import { ChatInputComponent } from "./chatInput";
import { ChatHistory } from "./chatHistory";
import { ActionButton, DropdownButton } from "../webui/components/buttons";
import { iconAIModel, iconDropdown, iconSettings, iconTrash } from "../icons";
import { iconBars } from "../webui/icons";
import { ConfirmCancelPopup } from "../webui/components/popup";
import { LLMs } from "./utils/llms";
import { settings_popup } from "./settings_popup";
import { Conversation } from "./model/conversation";
import { ConversationManager, ConversationManagerListener } from "./model/conversationManager";

export class ChatView extends Module<HTMLDivElement> {
    private llm: DropdownButton
    
    public constructor() {
        super("div", "", "chat")
        let header = new Module<HTMLDivElement>("div", "", "chat-header")
        let conversations = new ActionButton(iconBars)
        header.add(conversations)
        let newConversation = new ActionButton(iconTrash)
        header.add(newConversation)
        let quick_settings = new Module<HTMLSpanElement>("span", "", "fill-width")
        this.llm = new DropdownButton(iconAIModel + " loading... " + iconDropdown, null, true)
        let conversation = ConversationManager.getCurrentConversation()
        if (conversation) {
            this.setModel(conversation.getModel())
        }
        this.llm.onAction = async () => {
            let models = await LLMs.getInstance().getModels()
            let actions = new Map<string, CallableFunction>()
            for (let model of models) {
                actions.set(model, () => {
                    let conversation = ConversationManager.getCurrentConversation()
                    if (conversation) {
                        conversation.setModel(model)
                        this.setModel(model)
                    }
                    return true
                })
            }
            this.llm.showMenu(actions)
        }
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
        this.add(new ChatHistory())
        this.add(new ChatInputComponent())

        newConversation.onAction = () => {
            let popup = new ConfirmCancelPopup("Are you sure? (Will delete the entire conversation history)", "Yes", "Cancel")
            popup.onConfirm = () => {
                // FIXME replace with creation of new conversation once we have a conversation list viewer
                //ConversationManager.newConversation()
                let conversation = ConversationManager.getCurrentConversation()
                if (conversation) {
                    conversation.deleteMessages(conversation.getMessages()[0])
                }
            }
            popup.onCancel = () => { }
        }

        settings.onAction = () => {
            settings_popup();
        }

        let listener = new ConversationManagerListener()
        listener.onConversationSelected = (_id: string, conversation: Conversation) => {
            this.setModel(conversation.getModel())
        }
        ConversationManager.addListener(listener)
    }

    private setModel(model: string): void {
        this.llm.htmlElement.innerHTML = iconAIModel + " " + model + " " + iconDropdown
    }

    public update(_kwargs: KWARGS, _changedPage: boolean): void { }
}
