import "./chatInput.css"
import { iconCall, iconMicrophone, iconPlus, iconSend, iconTool, iconWeb, iconBook, iconTrash } from "../icons";
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
            let text = this.input.htmlElement.value
            let images: string[] = []
            let chat = this.parent! as Chat
            for (let module of media.getChildren()) {
                let image = module as Image
                images.push(image.getImageURL())
            }
            media.removeChildren()
            media.hide()
            chat.sendMessage(text, images)
            this.input.htmlElement.value = ""
            this.onUpdateInput()
        }

        this.input.htmlElement.addEventListener('paste', async (e) => {
            const clipboardItems = typeof navigator?.clipboard?.read === 'function' ? await navigator.clipboard.read() : e.clipboardData!.files

            for (const clipboardItem of clipboardItems) {
                if ((clipboardItem instanceof File) && (clipboardItem.type?.startsWith('image/'))) {
                    appendImage(clipboardItem)
                    e.preventDefault()
                } else if (clipboardItem instanceof ClipboardItem) {
                    // For files from `navigator.clipboard.read()`.
                    const imageTypes = clipboardItem.types?.filter((type: string) => type.startsWith('image/'))
                    for (const imageType of imageTypes) {
                        // Do something with the blob.
                        appendImage(await clipboardItem.getType(imageType))
                        e.preventDefault()
                    }
                }
            }
        })

        const appendImage = (blob: Blob) => {
            var reader = new FileReader()
            reader.readAsDataURL(blob)
            reader.onloadend = function () {
                var base64data = "" + reader.result
                let image = new Image(base64data)
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


class Image extends Module<HTMLImageElement> {
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
        alert("Not yet implemented!")
    }
}