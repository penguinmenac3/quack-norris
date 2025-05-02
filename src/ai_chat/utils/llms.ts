export enum APIType {
    OpenAI = "OpenAI",
    AzureOpenAI = "AzureOpenAI"
}

export interface IChatMessage {
    getText(): string
    getImages(): string[]
    getRole(): string
}

interface APIConnection {
    apiEndpoint: string;
    apiKey: string;
    type: APIType;
}


export class LLMs {
    private static instance = new LLMs()

    public static getInstance(): LLMs {
        return this.instance
    }

    private connections: APIConnection[] = []
    private models = new Map<string, number>()

    private constructor() {
        if (localStorage["quack-norris-llms"]) {
            this.connections = JSON.parse(localStorage["quack-norris-llms"])
        } else {
            this.addConnection("http://localhost:11434/v1", "")
        }
    }

    public async addConnection(apiEndpoint: string, apiKey: string, type: APIType = APIType.OpenAI): Promise<boolean> {
        this.connections.push({
            "apiEndpoint": apiEndpoint,
            "apiKey": apiKey,
            "type": type
        })
        localStorage["quack-norris-llms"] = JSON.stringify(this.connections)
        return true
    }

    public async getModels(): Promise<string[]> {
        let models = []
        this.models.clear()
        let idx = 0
        for (let connection of this.connections) {
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
                    let modelname = model["id"]
                    models.push(modelname)
                    this.models.set(modelname, idx)
                }
                idx += 1
            } catch { console.log("Failed to connect to " + connection.apiEndpoint) }
        }
        return models.sort()
    }

    public async* chat(model: string, history: IChatMessage[]): AsyncGenerator<string, void> {
        let idx = this.models.get(model)
        if (idx === undefined) {
            yield "ERROR: The model '" + model + "' is unavailable. Check your llm connections."
            return
        }
        let connection = this.connections[idx]

        if (connection.type == APIType.OpenAI) {
            let messages = []
            for (let message of history) {
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
                messages.push({
                    "role": message.getRole(),
                    "content": content
                })
            }

            // Stream in the result into the message entity
            try {
                const response = await fetch(connection.apiEndpoint + "/chat/completions", {
                    method: 'POST',
                    headers: {
                        Authorization: `Bearer ${connection.apiKey}`,
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        model: model,
                        messages: messages,
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

    public async embed(model: string, text: string) {
        let idx = this.models.get(model)
        if (!idx) return
        let connection = this.connections[idx]

        if (connection.type == APIType.OpenAI) {
            return "TODO OpenAI API Embed"
        } else if (connection.type == APIType.AzureOpenAI) {
            return "TODO AzureOpenAI API Embed"
        } else {
            return "Unsupported API"
        }
    }
}