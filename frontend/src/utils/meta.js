export function updateMetaTags(title, description) {
    if (title) {
        document.title = `${title} | Integr8sCode`;
    }
    
    if (description) {
        let metaDescription = document.querySelector('meta[name="description"]');
        if (!metaDescription) {
            metaDescription = document.createElement('meta');
            metaDescription.name = 'description';
            document.head.appendChild(metaDescription);
        }
        metaDescription.content = description;
    }
}

export const pageMeta = {
    home: {
        title: 'Home',
        description: 'Integr8sCode - Write, compile, and manage code directly in your browser with our powerful online development environment'
    },
    editor: {
        title: 'Code Editor',
        description: 'Online code editor with syntax highlighting, multi-language support, and real-time compilation. Write and test your code instantly in the browser'
    },
    login: {
        title: 'Login',
        description: 'Sign in to Integr8sCode to access your saved projects, code snippets, and personalized development environment'
    },
    register: {
        title: 'Register',
        description: 'Create a free Integr8sCode account to save your projects, collaborate with others, and access advanced coding features'
    }
};