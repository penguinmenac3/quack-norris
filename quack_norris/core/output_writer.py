from asyncio import Queue


class OutputWriter:
    @staticmethod
    def get_writer(shared: dict) -> 'OutputWriter':
        if "writer" not in shared:
            shared["writer"] = OutputWriter()
        return shared["writer"]

    def __init__(self, queue: Queue | None = None):
        self._state = "default"
        self._topic = "default"
        self._queue = queue

    async def thought(self, text: str, end="\n\n") -> None:
        await self.write(text + end, message_type="thought")

    async def default(self, text: str, end="\n\n") -> None:
        await self.write(text + end, message_type="default")

    async def detail(self, topic: str, text: str, end="\n\n") -> None:
        await self.write(text + end, message_type=topic)

    async def write(self, text: str, message_type: str | None = None, clean=True) -> None:
        if message_type is not None:
            await self._change_state(message_type)
        if self._queue is not None:
            # Remove all unwanted thinks, they should be handled explicitly
            if clean:
                text = text.replace("<think>", "")
                text = text.replace("</think>", "")
            await self._queue.put(text)
            await self._queue.put("")  # To trigger flushing
        else:
            print(text, end="")

    async def _change_state(self, state: str) -> None:
        topic: str = state
        state = state if state in ["default", "thought"] else "detail"
        if state != self._state:
            if self._state == "thought":
                await self.write("\n</think>\n", clean=False)
            elif self._state == "detail":
                await self.write("\n</details>\n", clean=False)
            if state == "thought":
                await self.write("\n<think>\n", clean=False)
            elif state == "detail":
                await self.write(f"\n<details><summary><b>{topic}:</b></summary>\n\n", clean=False)
        elif self._topic != topic:
            await self.write("\n</details>\n", clean=False)
            await self.write(f"\n<details><summary><b>{topic}:</b></summary>\n\n", clean=False)
        self._state = state
        self._topic = topic

    async def clear(self):
        # Reset mode to default
        await self.default("", end="")
