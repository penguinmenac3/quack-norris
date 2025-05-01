import './webui/core.css'
import './webui/colors.css'
import { STRINGS, setupLanguage } from './language/default'
import { PageManager } from './webui/pagemanager'
import { Chat } from './components/chat'


async function main() {
  setupLanguage()
  document.getElementsByTagName("title")[0].innerHTML = STRINGS.APPNAME
  new PageManager(
    "chat",
    {
      chat: new Chat("http://localhost:11337", ""),
    }
  )
}

main()