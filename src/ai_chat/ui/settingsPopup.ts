import { iconTrash } from "../../icons";
import { ActionButton } from "../../webui/components/buttons";
import { FormHeading, FormLabel, FormInput, FormRadioButtonGroup, FormSubmit, FormVSpace } from "../../webui/components/form";
import { ExitablePopup } from "../../webui/components/popup";
import { Module } from "../../webui/module";
import { LLMs, APIType } from "../logic/llms";
import { Tools } from "../logic/tools";


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
    // LLMs
    popup.add(new FormHeading("LLM Connections"));
    let connections = LLMs.getInstance().getConnections();
    for (let connection of connections) {
        popup.add(new RemovableItem(
            connection.name + " (" + connection.apiEndpoint + ")",
            () => { LLMs.getInstance().removeConnection(connection); }
        ));
    }
    popup.add(new FormHeading("Add LLM Server", "h2"));
    popup.add(new FormLabel("name"));
    let apiName = new FormInput("apiName", "Ollama", "text");
    popup.add(apiName);
    popup.add(new FormLabel("apiEndpoint"));
    let apiEndpoint = new FormInput("apiEndpoint", "https://localhost:11434/v1", "text");
    popup.add(apiEndpoint);
    popup.add(new FormLabel("apiKey"));
    let apiKey = new FormInput("apiKey", "f5a20...", "password");
    popup.add(apiKey);
    popup.add(new FormLabel("model"));
    let model = new FormInput("model", "(leave blank for autodetect)", "text");
    popup.add(model);
    popup.add(new FormLabel("apiType"));
    let apiTypeOptions = [APIType.OpenAI, APIType.AzureOpenAI];
    let apiType = new FormRadioButtonGroup("apiType", apiTypeOptions);
    apiType.value(0);
    popup.add(apiType);
    let addLLM = new FormSubmit("Add LLM Server", "buttonWide");
    addLLM.onClick = () => {
        let selectedApi = apiType.value() as any;
        if (!(selectedApi instanceof String)) {
            selectedApi = apiTypeOptions[selectedApi];
        }
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
        LLMs.getInstance().addConnection(
            apiName.value(),
            apiEndpoint.value(),
            apiKey.value(),
            model.value(),
            selectedApi
        );
        popup.dispose();
    };
    popup.add(addLLM);
    // Tools
    popup.add(new FormVSpace("3em"));
    popup.add(new FormHeading("Tool Connections"));
    let tools = Tools.getInstance().getConnections();
    for (let connection of tools) {
        popup.add(new RemovableItem(
            connection.apiEndpoint,
            () => { Tools.getInstance().removeConnection(connection); }
        ));
    }
    popup.add(new FormHeading("Add Tool Server", "h2"));
    popup.add(new FormLabel("toolEndpoint"));
    let toolEndpoint = new FormInput("toolEndpoint", "https://localhost:1337", "text");
    popup.add(toolEndpoint);
    popup.add(new FormLabel("toolKey"));
    let toolKey = new FormInput("toolKey", "f5a20...", "password");
    popup.add(toolKey);
    let addTool = new FormSubmit("Add Tool Server", "buttonWide");
    addTool.onClick = () => {
        Tools.getInstance().addConnection(toolEndpoint.value(), toolKey.value());
        popup.dispose();
    };
    popup.add(addTool);
}
