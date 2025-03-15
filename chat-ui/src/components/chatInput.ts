import "./chatInput.css"
import { iconCall, iconDropdown, iconMicrophone, iconPlus, iconTool } from "../icons";
import { Module } from "../webui/module";

export class ChatInput extends Module<HTMLDivElement> {
    public constructor() {
        super("div", "", "chat-input");
        this.htmlElement.innerHTML = this.createChatInputHTML();
    }

    private createChatInputHTML(): string {
        return `
            <div class="container">
                <textarea placeholder="Why is the sky blue?"></textarea>
                <div class="tool-bar">
                    <span class="action">`+ iconPlus + `</span>
                    <span class="settings">
                        <span class="dropdown">Quack Norris ` + iconDropdown + `</span>
                        <span class="dropdown">`+ iconTool + ` Tools ` + iconDropdown + `</span>
                    </span>
                    <span class="action">`+ iconMicrophone + `</span>
                    <span class="action">`+ iconCall + `</span>
                </div>
            </div>
        `;
    }
}