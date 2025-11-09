from asyncio import Queue


class OutputWriter:
    def __init__(self, queue: Queue | None = None):
        self._state = "default"
        self._topic = "default"
        self._queue = queue
        self.output_buffer = ""

    async def thought(self, text: str, separate=True) -> None:
        await self.write(text, message_type="thought", separate=separate)

    async def default(self, text: str, separate=True) -> None:
        await self.write(text, message_type="default", separate=separate)

    async def detail(self, topic: str, text: str, separate=True) -> None:
        await self.write(text, message_type=topic, separate=separate)

    async def write(
        self, text: str, message_type: str | None = None, separate=True, clean=True
    ) -> None:
        state_changed = False
        if message_type is not None:
            state_changed = await self._change_state(message_type)
        if separate and not state_changed:
            text = "\n\n" + text
        if self._queue is not None:
            # Remove all unwanted thinks, they should be handled explicitly
            if clean:
                text = text.replace("<think>", "")
                text = text.replace("</think>", "")
            await self._queue.put(text)
            await self._queue.put("")  # To trigger flushing
        else:
            print(text, end="")
        self.output_buffer += text

    async def _change_state(self, state: str) -> bool:
        state_changed = False
        topic: str = state
        state = state if state in ["default", "thought"] else "detail"
        if state != self._state:
            state_changed = True
            if self._state == "thought":
                await self.write("\n</think>\n", clean=False, separate=False)
            elif self._state == "detail":
                await self.write("\n</details>\n", clean=False, separate=False)
            if state == "thought":
                await self.write("\n<think>\n", clean=False, separate=False)
            elif state == "detail":
                await self.write(
                    f"\n<details><summary><b>{topic}:</b></summary>\n\n",
                    clean=False,
                    separate=False,
                )
        elif self._topic != topic:
            state_changed = True
            await self.write("\n</details>\n", clean=False, separate=False)
            await self.write(
                f"\n<details><summary><b>{topic}:</b></summary>\n\n",
                clean=False,
                separate=False,
            )
        self._state = state
        self._topic = topic
        return state_changed

    async def clear(self):
        # Reset mode to default
        await self.default("", separate=False)
