import "./chatInput.css"
import { iconCall, iconMicrophone, iconPlus, iconSend, iconTool, iconWeb, iconBook, iconTrash } from "../icons";
import { Module } from "../webui/module";
import { ActionButton } from "../webui/components/buttons";
import { ExitablePopup } from "../webui/components/popup";
import { FormInput, FormSubmit } from "../webui/components/form";
import { Conversation, ConversationListener } from "./model/conversation";
import { ConversationManager, ConversationManagerListener } from "./model/conversationManager";

export class ChatInputComponent extends Module<HTMLDivElement> {
    private input: Module<HTMLTextAreaElement>
    private send: ActionButton
    private call: ActionButton

    public constructor() {
        super("div", "", "chat-input");
        let container = new Module<HTMLDivElement>("div", "", "container")
        let media = new Module<HTMLDivElement>("div", "", "media")
        media.hide()
        container.add(media)
        this.input = new Module<HTMLTextAreaElement>("textarea")
        this.input.htmlElement.placeholder = "Why is the sky blue?"
        container.add(this.input)
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
            let conversation = ConversationManager.getCurrentConversation()
            if (!conversation) return
            let text = this.input.htmlElement.value
            let images: string[] = []
            for (let module of media.getChildren()) {
                let image = module as InputImageComponent
                images.push(image.getImageURL())
            }
            media.removeChildren()
            media.hide()
            conversation.sendMessage(text, images)
            this.input.htmlElement.value = ""
            this.onUpdateInput()
            conversation.setDraftText(this.input.htmlElement.value)
        }

        this.input.htmlElement.addEventListener('paste', async (e) => {
            const clipboardItems = typeof navigator?.clipboard?.read === 'function' ? await navigator.clipboard.read() : e.clipboardData!.files

            for (const clipboardItem of clipboardItems) {
                if ((clipboardItem instanceof File) && (["image/png", "image/jpeg"].includes(clipboardItem.type))) {
                    appendImage(clipboardItem)
                    e.preventDefault()
                } else if (clipboardItem instanceof ClipboardItem) {
                    // For files from `navigator.clipboard.read()`.
                    const imageTypes = clipboardItem.types?.filter((type: string) => ["image/png", "image/jpeg"].includes(type))
                    for (const imageType of imageTypes) {
                        // Do something with the blob.
                        appendImage(await clipboardItem.getType(imageType))
                        e.preventDefault()
                    }
                }
            }
        })

        let timer = 0
        container.htmlElement.ondragover = (ev: DragEvent) => {
            ev.preventDefault()
            if (ev.dataTransfer) {
                container.setClass("ondrag")
                if (timer != 0) {
                    window.clearTimeout(timer)
                    timer = 0
                }
                timer = window.setTimeout(() => { container.unsetClass("ondrag"); timer = 0 }, 200)
            }
        }

        container.htmlElement.ondrop = (ev: DragEvent) => {
            ev.preventDefault()
            if (ev.dataTransfer) {
                container.unsetClass("ondrag")
                let data = ev.dataTransfer.files
                for (let file of data) {
                    console.log(file.type)
                    if (["image/png", "image/jpeg"].includes(file.type)) {
                        appendImage(file)
                    }
                }
            }
        }

        addMedia.onAction = () => {
            let popup = new ExitablePopup()
            popup.add(new Module<HTMLDivElement>("div", "Add Image", "chat-add-media-header"))
            let image_file = new FormInput("image", "your image", "file")
            image_file.setClass("chat-add-media-input")
            image_file.htmlElement.accept = "image/png, image/jpeg"
            popup.add(image_file)
            let submit = new FormSubmit("Upload")
            submit.onClick = () => {
                let files = image_file.htmlElement.files
                if (files == null || files.length == 0) {
                    return
                }
                for (let file of files) {
                    if (["image/png", "image/jpeg"].includes(file.type)) {
                        appendImage(file)
                    }
                }
                popup.dispose()
            }
            popup.add(submit)
        }

        const appendImage = (blob: Blob) => {
            var reader = new FileReader()
            reader.readAsDataURL(blob)
            reader.onloadend = function () {
                var base64data = "" + reader.result
                let image = new InputImageComponent(base64data)
                image.onRemove = () => {
                    media.remove(image)
                    if (media.getChildren().length == 0) {
                        media.hide()
                    }
                }
                media.add(image)
                media.show()
            }
        }

        let conversation = ConversationManager.getCurrentConversation()
        if (conversation)
            this.registerConversationListener(conversation)
        let listener = new ConversationManagerListener()
        listener.onConversationSelected = (_id: string, conversation: Conversation) => {
            this.registerConversationListener(conversation);
        }
    }

    private registerConversationListener(conversation: Conversation) {
        let conversationListener = new ConversationListener();
        conversationListener.onDraftChanged = (draft_text: string, _draft_images: string[]) => {
            console.log(draft_text);
            this.input.htmlElement.value = draft_text;
            this.onUpdateInput();
            // TODO handle storing of images correctly
        };
        conversation.addListener(conversationListener);
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
}


class InputImageComponent extends Module<HTMLImageElement> {
    public constructor(private base64data: string) {
        super("div", "", "image")
        let image = new Module<HTMLImageElement>("img")
        image.htmlElement.src = base64data
        this.add(image)
        let remove = new ActionButton(iconTrash, () => { this.onRemove() })
        this.add(remove)
    }

    public getImageURL(): string {
        return this.base64data
    }

    public onRemove() {
        alert("Must be overwritten by creator!")
    }
}