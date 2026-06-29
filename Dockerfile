FROM node:20-alpine

# Install pnpm
RUN npm install -g pnpm

# Set working directory
WORKDIR /app

# Copy package files
COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml* ./

# Install dependencies
RUN pnpm install

# Copy the rest of the application
COPY . .

# Build the frontend
RUN pnpm run build

# Expose the port the app runs on
EXPOSE 8080

# Command to run the application
CMD ["pnpm", "run", "serve"]
