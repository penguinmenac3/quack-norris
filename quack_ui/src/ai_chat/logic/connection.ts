import { ChatMessage } from "./chatMessage"


interface APIConnection {
    name: string
    apiEndpoint: string
    apiKey: string
}


export class Connection {
    private static instance = new Connection()

    public static getInstance(): Connection {
        return this.instance
    }

    private connections = new Map<string, APIConnection>()

    private constructor() {
        if (localStorage["quack-norris-llms"] && localStorage["quack-norris-llms"] != "[]") {
            this.connections = new Map(JSON.parse(localStorage["quack-norris-llms"]))
        } else {
            this.addConnection("local", "http://localhost:11435", "")
        }
    }

    public getConnections(): APIConnection[] {
        return Array.from(this.connections.values())
    }

    public async addConnection(name: string, apiEndpoint: string, apiKey: string): Promise<boolean> {
        this.connections.set(name, {
            "name": name,
            "apiEndpoint": apiEndpoint,
            "apiKey": apiKey
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
            idx += 1
        }
        return models.sort()
    }

    public async getWorkspaces(model: string): Promise<string[]> {
        let workspaces: string[] = []
        let [connectionName, _modelName] = model.split("/")
        let connection = this.connections.get(connectionName)
         if (!connection) {
            console.log("Unknown connection for " + model)
            return workspaces
        }
        try {
            const response = await fetch(connection.apiEndpoint + "/workspaces", {
                method: 'GET',
                headers: {
                    Authorization: `Bearer ${connection.apiKey}`,
                    'Content-Type': 'application/json',
                },
            })
            workspaces = await response.json()
        } catch {
            console.log("Server does not support workspaces or failed to connect to " + connection.apiEndpoint)
            return workspaces
        }
        return workspaces
    }

    public async* stream(model: string, workspace: string, messages: ChatMessage[]): AsyncGenerator<string, void> {
        let [connectionName, modelName] = model.split("/")
        let connection = this.connections.get(connectionName)
        if (!connection) {
            yield "ERROR: The model '" + model + "' is unavailable. Check your llm connections."
            return
        }

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
                    workspace: workspace,
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
}