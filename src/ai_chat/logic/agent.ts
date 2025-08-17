import { ChatMessage } from "./chatMessage"
import { LLMs } from "./llms"

export class Agent {
    private static instance = new Agent()

    public static getInstance(): Agent {
        return this.instance
    }

    private constructor() {}

    public async* chat(model: string, messages: ChatMessage[], settings: { [key: string]: any }): AsyncGenerator<string, void> {
        let llm = LLMs.getInstance()
        if (!this.hasTools(settings.web) && !this.hasTools(settings.rag) && !this.hasTools(settings.tools)) {
            let stream = llm.stream(model, messages)
            for await (let token of stream) {
                yield token
            }
        } else {
            // Context Retriever
            console.log("TODO context retriever and tool calling not yet implemented")

            // Aggregator
            console.log("TODO adding a message to prompt aggregator with context still missing")
            let stream = llm.stream(model, messages)
            for await (let token of stream) {
                yield token
            }
        }
    }

    private hasTools(toolList: { [key: string]: any }): boolean {
        if (!toolList) return false
        return Object.keys(toolList).length > 0
    }
}