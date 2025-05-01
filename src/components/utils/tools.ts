
export interface Tool {
    connection_idx: number
    name: string
    description: string
    arg_schema: string
}

interface APIConnection{
    apiEndpoint: string;
    apiKey: string;
}


export class Tools {
    private static instance = new Tools()

    public static getInstance(): Tools {
        return this.instance
    }

    private connections: APIConnection[] = []
    private tool_groups = new Map<string, string[]>()
    private tools = new Map<string, Tool>()
    private authorized_tools: string[] = []

    private constructor() {}

    public async addConnection(apiEndpoint: string, apiKey: string): Promise<boolean> {
        this.connections.push({
            "apiEndpoint": apiEndpoint,
            "apiKey": apiKey
        })
        return true
    }

    private async updateTools(): Promise<void> {
        // TODO get all tools from all connections and assign them to the tool_groups
    }

    public async getToolGroups(): Promise<string[]> {
        await this.updateTools()
        return Array.from(this.tool_groups.keys())
    }

    public async getTools(groups: string[]): Promise<Tool[]> {
        await this.updateTools()
        let result: Tool[] = []
        for (let [group_name, group_tools] of this.tool_groups) {
            if (groups.includes(group_name)) {
                for (let tool_name of group_tools) {
                    let tool = this.tools.get(tool_name)
                    if (tool) {
                        result.push(tool)
                    }
                }
            }
        }
        return result
    }

    public async callTool(tool_name: string, args: any): Promise<string> {
        if (!this.authorized_tools.includes(tool_name)) {
            // TODO ask for permission from user (always, once, decline)
            // TODO always -> add to authorized_tools
            // TODO decline -> return an error message that user permission was not given
        }
        let tool = this.tools.get(tool_name)
        if (!tool) {
            return "ERROR: Tool not found '" + tool_name + "', name does not exist in tools."
        }
        let connection = this.connections[tool.connection_idx]
        // TODO validate args against arg_schema
        // TODO send args to connection
        return ""
    }
}