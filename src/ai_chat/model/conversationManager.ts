import { v4 as uuid } from "uuid";
import { Conversation } from "./conversation";


export class ConversationManagerListener {
    public onConversationAdded(_id: string, _name: string, _modified: string): void { }
    public onConversationRenamed(_id: string, _name: string, _modified: string): void { }
    public onConversationModified(_id: string, _name: string, _modified: string): void { }
    public onConversationRemoved(_id: string): void { }
    public onConversationSelected(_id: string, _conversation: Conversation): void { }
}

export class ConversationManager {
    private constructor() { }
    private static listeners: ConversationManagerListener[] = [];
    private static currentConversation: Conversation | null = null;

    public static addListener(listener: ConversationManagerListener): void {
        ConversationManager.listeners.push(listener);
    }
    public static removeListener(listener: ConversationManagerListener): void {
        let idx = ConversationManager.listeners.indexOf(listener);
        if (idx >= 0) {
            ConversationManager.listeners.splice(idx, 1);
        }
    }
    public static clearListeners(): void {
        ConversationManager.listeners = [];
    }

    public static getConversations(): any {
        /**
         * A dictionary mapping ids to name and last modified.
         * {"<id>": {"name": "<name>", "modified": "<iso-string>"}}
         */
        if (localStorage["quack-norris-conversations"])
            return JSON.parse(localStorage["quack-norris-conversations"]);

        else
            return {};
    }
    public static saveConversation(conversation: Conversation): void {
        let id = conversation.getID();
        if (id == "")
            throw Error("Cannot save conversation without an ID.");
        let conversations = ConversationManager.getConversations();
        if (!conversations[id])
            throw Error("Invalid ID, ID does not exist and cannot be renamed. ID: " + id);
        let modified = new Date().toISOString();
        conversations[id]["modified"] = modified;
        localStorage["quack-norris-conversations"] = JSON.stringify(conversations);
        localStorage["quack-norris-conversation-" + id] = conversation.toJSON();
        for (let listener of ConversationManager.listeners) {
            listener.onConversationModified(id, conversations[id]["name"], conversations);
        }
    }
    public static selectConversation(id: string): boolean {
        let conversations = ConversationManager.getConversations();
        if (!conversations[id])
            return false;
        if (!localStorage["quack-norris-conversation-" + id])
            return false;
        if (ConversationManager.currentConversation?.getID() == id)
            return true; // skip loading if it is already active

        ConversationManager.currentConversation = Conversation.fromJSON(id, localStorage["quack-norris-conversation-" + id]);
        for (let listener of ConversationManager.listeners) {
            listener.onConversationSelected(id, ConversationManager.currentConversation);
        }
        return true;
    }
    public static getCurrentConversation(): Conversation | null {
        return ConversationManager.currentConversation;
    }
    public static newConversation(): void {
        let model = localStorage["quack-norris-default-model"] || "select model";
        let conversation = new Conversation(model);
        let id = ConversationManager.addConversation("unnamed", conversation);
        ConversationManager.selectConversation(id);
    }

    public static addConversation(name: string, conversation: Conversation): string {
        let conversations = ConversationManager.getConversations();
        let id = uuid();
        while (conversations[id]) {
            id = uuid();
        }
        conversation.setID(id);
        let modified = new Date().toISOString();
        conversations[id] = { "name": name, "modified": modified };
        localStorage["quack-norris-conversations"] = JSON.stringify(conversations);
        ConversationManager.saveConversation(conversation);
        for (let listener of ConversationManager.listeners) {
            listener.onConversationAdded(id, name, modified);
        }
        return id;
    }
    public static renameConversation(id: string, name: string): void {
        let conversations = ConversationManager.getConversations();
        if (!conversations[id])
            throw Error("Invalid ID, ID does not exist and cannot be renamed. ID: " + id);
        let modified = new Date().toISOString();
        conversations[id] = { "name": name, "modified": modified };
        localStorage["quack-norris-conversations"] = JSON.stringify(conversations);
        for (let listener of ConversationManager.listeners) {
            listener.onConversationRenamed(id, name, modified);
        }
    }
    public static removeConversation(id: string): void {
        let conversations = ConversationManager.getConversations();
        if (!conversations[id])
            throw Error("Invalid ID, ID does not exist and cannot be renamed. ID: " + id);
        delete conversations[id];
        delete localStorage["quack-norris-conversation-" + id];
        localStorage["quack-norris-conversations"] = JSON.stringify(conversations);
        for (let listener of ConversationManager.listeners) {
            listener.onConversationRemoved(id);
        }
    }
}
