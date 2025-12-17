import "./chat.css"
import { KWARGS, Module } from "../../webui/module";
import { ChatInputComponent } from "./chatInput";
import { ChatHistory } from "./chatHistory";
import { ActionButton } from "../../webui/components/buttons";
import { iconEdit, iconSettings, iconTrash } from "../../icons";
import { iconBars } from "../../webui/icons";
import { ConfirmCancelPopup } from "../../webui/components/popup";
import { settingsPopup } from "./settingsPopup";
import { ConversationManager, ConversationManagerListener } from "../logic/conversationManager";

export class ChatView extends Module<HTMLDivElement> {
    public constructor() {
        super("div", "", "chat")
        let header = new Module<HTMLDivElement>("div", "", "chat-header")
        let conversations = new ActionButton(iconBars)
        header.add(conversations)
        let center_fill = new Module<HTMLSpanElement>("span", "", "fill-width")
        center_fill.setClass("main-header")
        let chat_heading = new Module<HTMLSpanElement>("span", "Unnamed Chat")
        chat_heading.setClass("centered-text")
        center_fill.add(chat_heading)
        let editHeading = new ActionButton(iconEdit)
        editHeading.htmlElement.style.fontSize = "0.8em"
        editHeading.htmlElement.style.marginLeft = "0.4em"
        editHeading.htmlElement.style.fontWeight = "normal"
        center_fill.add(editHeading)
        header.add(center_fill)
        let newConversation = new ActionButton(iconTrash)
        header.add(newConversation)
        let settings = new ActionButton(iconSettings)
        header.add(settings)
        this.add(header)
        this.add(new ChatHistory())
        this.add(new ChatInputComponent())

        ConversationManager.addListener(new class extends ConversationManagerListener {
            onCurrentConversationChanged(): void {
                let conversation = ConversationManager.getCurrentConversation()
                if (conversation) {
                    chat_heading.htmlElement.textContent = conversation.getName()
                }
            }
        })

        editHeading.onAction = () => {
            chat_heading.htmlElement.textContent = prompt("Rename chat:", chat_heading.htmlElement.textContent || "Unnamed Chat") || "Unnamed Chat "
            let conversation = ConversationManager.getCurrentConversation()
            if (conversation) {
                conversation.setName(chat_heading.htmlElement.textContent.trim())
            }
        }

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
            settingsPopup();
        }
    }

    public update(_kwargs: KWARGS, _changedPage: boolean): void { }
}
