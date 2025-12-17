import { iconTrash } from "../../icons";
import { ActionButton } from "../../webui/components/buttons";
import { FormHeading, FormLabel, FormInput, FormSubmit } from "../../webui/components/form";
import { ExitablePopup } from "../../webui/components/popup";
import { Module } from "../../webui/module";
import { Connection } from "../logic/connection";


class RemovableItem extends Module<HTMLDivElement> {
    constructor(text: string, callback: CallableFunction) {
        super("div", text, "removableItem")
        let button = new ActionButton(iconTrash)
        button.setClass("right")
        button.onAction = () => { this.hide(); callback() }
        this.add(button)
    }
}

export function settingsPopup() {
    let popup = new ExitablePopup("popupContent-fullscreen");
    popup.add(new FormHeading("Connections"));
    let connections = Connection.getInstance().getConnections();
    for (let connection of connections) {
        popup.add(new RemovableItem(
            connection.name + " (" + connection.apiEndpoint + ")",
            () => { Connection.getInstance().removeConnection(connection); }
        ));
    }
    popup.add(new FormHeading("Add Connection", "h2"));
    popup.add(new FormLabel("name"));
    let apiName = new FormInput("apiName", "Ollama", "text");
    popup.add(apiName);
    popup.add(new FormLabel("apiEndpoint"));
    let apiEndpoint = new FormInput("apiEndpoint", "localhost:11435", "text");
    popup.add(apiEndpoint);
    popup.add(new FormLabel("apiKey"));
    let apiKey = new FormInput("apiKey", "f5a20...", "password");
    popup.add(apiKey);
    let addLLM = new FormSubmit("Add Connection", "buttonWide");
    addLLM.onClick = () => {
        if (apiName.value() == "") {
            alert("name must not be empty!");
            return;
        }
        if (apiEndpoint.value() == "") {
            alert("apiEndpoint must not be empty!");
            return;
        }
        if (apiKey.value() == "") {
            alert("apiKey must not be empty!");
            return;
        }
        Connection.getInstance().addConnection(
            apiName.value(),
            apiEndpoint.value(),
            apiKey.value(),
        );
        popup.dispose();
    };
    popup.add(addLLM);
}
