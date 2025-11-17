pipeline {
    agent any

    environment {
        REGISTRY        = "dmmprice/powercasting_chatbot"
        CONTAINER_NAME  = "powercasting-chatbot"
        HOST_PORT       = "4003"    // exposed port on VPS
        CONTAINER_PORT  = "5050"    // Flask/gunicorn port inside container
    }

    triggers {
        githubPush()
    }

    stages {
        stage('Checkout') {
            steps {
                // If your default branch is not 'main', change it to 'master' or whatever is correct
                git branch: 'master', url: 'https://github.com/rikchowdhury22/PowerCasting_Chatbot.git'
            }
        }

        stage('Prepare .env (from Jenkins secret file)') {
            steps {
                // Create a Jenkins "Secret file" credential with ID: powercasting-chatbot-env-file
                withCredentials([file(credentialsId: 'powercasting-chatbot-env-file', variable: 'ENV_FILE')]) {
                    sh '''
                      echo "Copying env file from Jenkins credential to workspace as .env..."
                      cp "$ENV_FILE" .env
                    '''
                }
            }
        }

        stage('Build Docker image') {
            steps {
                script {
                    def imageTag = "${env.BUILD_NUMBER}"
                    sh """
                      echo "Building Docker image ${REGISTRY}:${imageTag} and tagging as latest..."
                      docker build \\
                        -t ${REGISTRY}:${imageTag} \\
                        -t ${REGISTRY}:latest \\
                        .
                    """
                }
            }
        }

        stage('Push Docker image') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'dockerhub-dmmprice',
                    usernameVariable: 'DOCKER_USER',
                    passwordVariable: 'DOCKER_PASS'
                )]) {
                    sh '''
                      echo "Logging in to Docker Hub..."
                      echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin

                      echo "Pushing image tags to Docker Hub..."
                      docker push ${REGISTRY}:${BUILD_NUMBER}
                      docker push ${REGISTRY}:latest

                      echo "Logging out from Docker Hub..."
                      docker logout
                    '''
                }
            }
        }

        stage('Deploy (destroy old container & start new)') {
            steps {
                withCredentials([file(credentialsId: 'powercasting-chatbot-env-file', variable: 'ENV_FILE')]) {
                    sh '''
                      echo "Stopping old container if exists..."
                      docker stop ${CONTAINER_NAME} || true

                      echo "Removing old container if exists..."
                      docker rm ${CONTAINER_NAME} || true

                      echo "Starting new container on port ${HOST_PORT}..."
                      docker run -d \
                        --name ${CONTAINER_NAME} \
                        --restart always \
                        -p ${HOST_PORT}:${CONTAINER_PORT} \
                        --env-file "$ENV_FILE" \
                        ${REGISTRY}:latest

                      echo "Deployment complete: ${CONTAINER_NAME} running on ${HOST_PORT} -> ${CONTAINER_PORT}"
                    '''
                }
            }
        }
    }

    post {
        always {
            // Clean up dangling images (safe, doesn’t remove tagged ones we just built)
            sh 'docker image prune -f || true'
        }
    }
}
