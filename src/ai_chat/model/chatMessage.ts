export class ChatMessageListener {
    public onExtendText(_text: string): void { }
}


export class ChatMessage {
    private listeners: ChatMessageListener[] = [];

    public constructor(
        private text: string = "",
        private images: string[] = [],
        private role: string = "user" // or modelname that was used)
    ) { }
    public addListener(listener: ChatMessageListener): void {
        this.listeners.push(listener);
    }
    public removeListener(listener: ChatMessageListener): void {
        let idx = this.listeners.indexOf(listener);
        if (idx >= 0) {
            this.listeners.splice(idx, 1);
        }
    }
    public getText(): string {
        return this.text;
    }
    public getImages(): string[] {
        return this.images;
    }
    public getRole(): string {
        return this.role;
    }
    public extendText(chunk: string): void {
        this.text += chunk;
        for (let listener of this.listeners) {
            listener.onExtendText(chunk);
        }
    }
}
