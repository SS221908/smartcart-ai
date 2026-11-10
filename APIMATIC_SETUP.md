# APIMatic PayPal Context Plugin

The APIMatic PayPal Context Plugin is for the **coding agent implementing PayPal**, not a runtime dependency inside SmartCart. It gives the coding assistant current PayPal SDK setup, authentication, endpoints, error handling, and testing guidance.

In the project terminal, install the plugin for the coding assistant:

```bash
npx context-plugins install paypal
```

Then ask the coding assistant to implement the PayPal Sandbox Orders flow using the installed PayPal API context. The SmartCart AI service must only return product recommendations and a user-approved cart; Person 2's checkout code creates and captures orders after the user approves. Keep PayPal credentials on the server.
