/**
 * @type {import('vite').UserConfig}
 */
const config = {
    // ...
    base: "/quack-norris/",
    server: {
        host: "localhost",
        watch: {
            ignored: ['!**/dist/'],
            usePolling: true
        }
    }
}

export default config