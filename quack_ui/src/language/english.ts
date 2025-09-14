
export class English  {
    protected constructor() {}

    public static APPLY_COUNTED(num: number, format: string): string {
        return format.replace("{count}", num.toString())
    }

    public static TIME_LOCALE = "en"
    public static TIME_YESTERDAY = "yesterday"
    public static TIME_HOURS_AGO = "{count} hour(s) ago"
    public static TIME_MINUTES_AGO = "{count} minute(s) ago"
    public static TIME_SECONDS_AGO = "{count} second(s) ago"
    public static TIME_TODAY_AT = "today at"
    public static TIME_JUST_NOW = "just now"

    public static APPNAME = "QuackNorris Chat"
}