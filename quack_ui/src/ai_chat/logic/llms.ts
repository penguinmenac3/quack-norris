import { ChatMessage } from "./chatMessage"

export enum APIType {
    OpenAI = "OpenAI",
    AzureOpenAI = "AzureOpenAI"
}

interface APIConnection {
    name: string
    apiEndpoint: string
    apiKey: string
    type: APIType
    model: string
}


export class LLMs {
    private static instance = new LLMs()

    public static getInstance(): LLMs {
        return this.instance
    }

    private connections = new Map<string, APIConnection>()

    private constructor() {
        if (localStorage["quack-norris-llms"]) {
            this.connections = new Map(JSON.parse(localStorage["quack-norris-llms"]))
        } else {
            this.addConnection("Ollama", "http://localhost:11434/v1", "", "")
        }
    }

    public getConnections(): APIConnection[] {
        return Array.from(this.connections.values())
    }

    public async addConnection(name: string, apiEndpoint: string, apiKey: string, model: string, type: APIType = APIType.OpenAI): Promise<boolean> {
        this.connections.set(name, {
            "name": name,
            "apiEndpoint": apiEndpoint,
            "apiKey": apiKey,
            "type": type,
            "model": model
        })
        localStorage["quack-norris-llms"] = JSON.stringify(Array.from(this.connections.entries()))
        return true
    }

    public removeConnection(connection: APIConnection): boolean {
        this.connections.delete(connection.name)
        localStorage["quack-norris-llms"] = JSON.stringify(Array.from(this.connections.entries()))
        return true
    }

    public async getModels(): Promise<string[]> {
        let models = []
        let idx = 0
        for (let connection of this.getConnections()) {
            if (connection.model != "") {
                models.push(connection.name + "/" + connection.model)
            } else {
                try {
                    const response = await fetch(connection.apiEndpoint + "/models", {
                        method: 'GET',
                        headers: {
                            Authorization: `Bearer ${connection.apiKey}`,
                            'Content-Type': 'application/json',
                        },
                    })
                    let data = await response.json()
                    for (let model of data["data"]) {
                        let modelname = connection.name + "/" + model["id"]
                        models.push(modelname)
                    }
                } catch { console.log("Failed to connect to " + connection.apiEndpoint) }
            }
            idx += 1
        }
        return models.sort()
    }

    public async chat(model: string, messages: ChatMessage[]): Promise<string> {
        let [connectionName, modelName] = model.split("/")
        let connection = this.connections.get(connectionName)
        if (!connection) {
            return "ERROR: The model '" + model + "' is unavailable. Check your llm connections."
        }

        if (connection.type == APIType.OpenAI) {
            let history = this.messagesToOpenAIFormat(messages)

            // Return the message content
            try {
                const response = await fetch(connection.apiEndpoint + "/chat/completions", {
                    method: 'POST',
                    headers: {
                        Authorization: `Bearer ${connection.apiKey}`,
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        model: modelName,
                        messages: history,
                        stream: false,
                    }),
                });
                let data = await response.json()
                return data.choices[0].message.content
            } catch {
                return "\n\nERROR: Failed to retrieve answer from the LLM."
            }
        } else if (connection.type == APIType.AzureOpenAI) {
            return "ERROR: AzureOpenAI chat endpoint not implemented yet!"
        } else {
            return "ERROR: Unsupported chat API type!"
        }
    }

    public async* stream(model: string, messages: ChatMessage[]): AsyncGenerator<string, void> {
        let [connectionName, modelName] = model.split("/")
        let connection = this.connections.get(connectionName)
        if (!connection) {
            yield "ERROR: The model '" + model + "' is unavailable. Check your llm connections."
            return
        }

        if (connection.type == APIType.OpenAI) {
            let history = this.messagesToOpenAIFormat(messages)

            // Stream in the result into the message entity
            try {
                const response = await fetch(connection.apiEndpoint + "/chat/completions", {
                    method: 'POST',
                    headers: {
                        Authorization: `Bearer ${connection.apiKey}`,
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        model: modelName,
                        messages: history,
                        stream: true,
                    }),
                });
                const reader = response.body?.pipeThrough(new TextDecoderStream()).getReader();
                if (!reader) return;
                // eslint-disable-next-line no-constant-condition
                while (true) {
                    // eslint-disable-next-line no-await-in-loop
                    const { value, done } = await reader.read();
                    if (done) break;
                    const arr = value.split('\n');
                    for (let data of arr) {
                        if (data.length === 0) continue // ignore empty message
                        if (data.startsWith(':')) continue // ignore sse comment message
                        if (data === 'data: [DONE]') return  // exit the stream if we are done
                        const json = JSON.parse(data.substring(6))
                        let text = json.choices[0]["delta"]["content"]
                        yield text
                    }
                }
            } catch {
                yield "\n\nERROR: Failed to retrieve answer from the LLM."
            }
        } else if (connection.type == APIType.AzureOpenAI) {
            yield "ERROR: AzureOpenAI chat endpoint not implemented yet!"
        } else {
            yield "ERROR: Unsupported chat API type!"
        }
    }

    private messagesToOpenAIFormat(messages: ChatMessage[]) {
        let history = []
        for (let message of messages) {
            let content: any[] = [{
                "type": "text",
                "text": message.getText()
            }]
            for (let image of message.getImages()) {
                content.push({
                    "type": "image_url",
                    "image_url": { "url": image }
                })
            }
            let role = message.getRole()
            if (role != "user" && role != "system") {
                role = "assistant"
            }
            history.push({
                "role": role,
                "content": content
            })
        }
        return history
    }

    public async embed(model: string, _text: string) {
        let [connectionName, _modelName] = model.split("/")
        let connection = this.connections.get(connectionName)
        if (!connection) {
            return "ERROR: The model '" + model + "' is unavailable. Check your llm connections."
        }

        if (connection.type == APIType.OpenAI) {
            return "TODO OpenAI API Embed"
        } else if (connection.type == APIType.AzureOpenAI) {
            return "TODO AzureOpenAI API Embed"
        } else {
            return "Unsupported API"
        }
    }
}