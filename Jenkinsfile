pipeline {
    agent any

    environment {
        REGISTRY        = "dmmprice/powercasting_chatbot"
        CONTAINER_NAME  = "powercasting-chatbot"
        HOST_PORT       = "4003"    // host port on VPS
        CONTAINER_PORT  = "5050"    // Flask/gunicorn port inside container
    }

    triggers {
        githubPush()
    }

    stages {
        stage('Checkout') {
            steps {
                // 👉 change URL/branch if your chatbot repo is different
                git branch: 'main', url: 'https://github.com/DMMPrice/powercasting_chatbot.git'
            }
        }

        stage('Prepare .env (from Jenkins secret file)') {
            steps {
                // Jenkins credential: secret file with your env vars
                // ID example: powercasting-chatbot-env-file
                withCredentials([file(credentialsId: 'powercasting-chatbot-env-file', variable: 'ENV_FILE')]) {
                    sh '''
                      echo "Copying env file from Jenkins credential to workspace..."
                      cp "$ENV_FILE" .env
                    '''
                }
            }
        }

        stage('Build Docker image (local)') {
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

        stage('Push Docker image (push local image to Docker Hub)') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'dockerhub-dmmprice',
                    usernameVariable: 'DOCKER_USER',
                    passwordVariable: 'DOCKER_PASS'
                )]) {
                    sh '''
                      echo "Logging in to Docker Hub..."
                      echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin

                      echo "Pushing local image tags to Docker Hub..."
                      docker push ${REGISTRY}:${BUILD_NUMBER}
                      docker push ${REGISTRY}:latest

                      echo "Docker logout..."
                      docker logout
                    '''
                }
            }
        }

        stage('Deploy (destroy old container and start new from local image)') {
            steps {
                withCredentials([file(credentialsId: 'powercasting-chatbot-env-file', variable: 'ENV_FILE')]) {
                    sh '''
                      echo "Using locally built image for deployment (no docker pull)..."

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

                      echo "Deployment complete: ${CONTAINER_NAME} on ${HOST_PORT} -> ${CONTAINER_PORT}"
                    '''
                }
            }
        }
    }

    post {
        always {
            // clean dangling images, but keep the ones we just built because they are tagged
            sh 'docker image prune -f || true'
        }
    }
}
