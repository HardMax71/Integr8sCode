<script>
    import { Route, Router } from "svelte-routing";
    import Home from "./routes/Home.svelte";
    import Login from "./routes/Login.svelte";
    import Register from "./routes/Register.svelte";
    import Editor from "./routes/Editor.svelte";
    import Header from "./components/Header.svelte";
    import Footer from "./components/Footer.svelte";
    import Notifications from "./components/Notifications.svelte";
    import { theme } from './stores/theme.js';

    $: themeValue = $theme;

    export let url = "";
</script>

<Router {url}>
    <div class="flex flex-col min-h-screen bg-bg-default dark:bg-dark-bg-default">
        <Header/>
        <div class="flex-grow flex flex-col">
            <Notifications/>
            <main class="flex-grow w-full max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
                <Route path="/" component={Home}/>
                <Route path="/editor" component={Editor}/>
                <Route path="/login" component={Login}/>
                <Route path="/register" component={Register}/>
            </main>
        </div>
        <Footer/>
    </div>
</Router>

<style>
    main {
        padding-top: 6rem;
        padding-bottom: 2rem;
    }
     @media (max-width: 768px) {
        main {
            padding-top: 5rem;
            padding-left: 1rem;
            padding-right: 1rem;
        }
    }

</style>