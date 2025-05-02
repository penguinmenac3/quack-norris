export enum APIType {
    OpenAI = "OpenAI",
    AzureOpenAI = "AzureOpenAI"
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
        }
        return models.sort()
    }

    public async chat(model: string, history: any) {
        let idx = this.models.get(model)
        if (!idx) return
        let connection = this.connections[idx]

        if (connection.type == APIType.OpenAI) {
            return "TODO OpenAI API Chat"
        } else if (connection.type == APIType.AzureOpenAI) {
            return "TODO AzureOpenAI API Chat"
        } else {
            return "Unsupported API"
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