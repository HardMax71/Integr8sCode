<script>
    import { Route, Router } from "svelte-routing";
    import Home from "./routes/Home.svelte";
    import Editor from "./routes/Editor.svelte";
    import Login from "./routes/Login.svelte";
    import Register from "./routes/Register.svelte";
    import Header from "./components/Header.svelte";
    import Footer from "./components/Footer.svelte";
    import Notifications from "./components/Notifications.svelte";

    export let url = "";
</script>

<Router {url}>
    <div class="app">
        <Header/>
        <Notifications/>
        <main>
            <Route path="/" component={Home}/>
            <Route path="/editor" component={Editor}/>
            <Route path="/login" component={Login}/>
            <Route path="/register" component={Register}/>
        </main>
        <Footer/>
    </div>
</Router>

<style>
    :global(body) {
        font-family: 'Roboto', sans-serif;
        background-color: #f5f5f5;
        color: #333;
        margin: 0;
        padding: 0;
    }

    .app {
        display: flex;
        flex-direction: column;
        min-height: 100vh;
    }

    main {
        flex: 1;
        padding: 2rem;
        max-width: 1200px;
        margin: 0 auto;
        width: 100%;
        box-sizing: border-box;
    }

    @media (max-width: 768px) {
        main {
            padding: 1rem;
        }
    }
</style>