export enum APIType {
    OpenAI,
    AzureOpenAI
}

interface APIConnection{
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

    private constructor() {}

    public async addConnection(apiEndpoint: string, apiKey: string, type: APIType): Promise<boolean> {
        this.connections.push({
            "apiEndpoint": apiEndpoint,
            "apiKey": apiKey,
            "type": type
        })
        return true
    }

    public async getModels(): Promise<string[]> {
        // TODO request models from all connections and collect them in the models map
        return []
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