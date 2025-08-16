import './webui/core.css'
import './webui/colors.css'
import { STRINGS, setupLanguage } from './language/default'
import { PageManager } from './webui/pagemanager'
import { ChatView } from './ai_chat/ui/chat'
import { ConversationManager } from "./ai_chat/logic/conversationManager"


async function main() {
  setupLanguage()
  document.getElementsByTagName("title")[0].innerHTML = STRINGS.APPNAME
  let conversations = Object.entries(ConversationManager.getConversations())
  if (conversations.length == 0) {
    ConversationManager.newConversation()
  } else {
    let latest = conversations.reduce((a: any, b: any) =>
      (a[1].modified > b[1].modified ? a : b)
    )
    let selected = ConversationManager.selectConversation(latest[0])
    if (!selected) {
      console.log("Could not select conversation:", latest[0])
    }
  }
  new PageManager(
    "chat",
    {
      chat: new ChatView(),
    }
  )
}

main()